from flask import Flask, request, make_response, jsonify
import openfisca_uk
from openfisca_core import periods
from openfisca_core.model_api import *
from openfisca_uk.entities import *
from openfisca_uk.tools.general import *
from flask_cors import CORS
from openfisca_uk.microdata.simulation import Microsimulation
from rdbl import gbp
import plotly.express as px
import logging
import json

app = Flask(__name__)
CORS(app)


SYSTEM = openfisca_uk.CountryTaxBenefitSystem()
baseline = openfisca_uk.Microsimulation()
baseline.calc("household_net_income")

def abolish_PA():
    class PA_reform(Reform):
        def apply(self):
            self.neutralize_variable("personal_allowance")
    return PA_reform

def change_basic_rate(value):
    def change_BR_param(parameters):
        parameters.tax.income_tax.rates.uk.brackets[0].rate.update(periods.period("year:2015:10"), value=value / 100)
        return parameters
    
    class basic_rate_reform(Reform):
        def apply(self):
            self.modify_parameters(change_BR_param)
    
    return basic_rate_reform

def change_higher_rate(value):
    def change_HR_param(parameters):
        parameters.tax.income_tax.rates.uk.brackets[1].rate.update(periods.period("year:2015:10"), value=value / 100)
        return parameters
    
    class basic_rate_reform(Reform):
        def apply(self):
            self.modify_parameters(change_HR_param)
    
    return basic_rate_reform

def change_add_rate(value):
    def change_AR_param(parameters):
        parameters.tax.income_tax.rates.uk.brackets[2].rate.update(periods.period("year:2015:10"), value=value / 100)
        return parameters
    
    class basic_rate_reform(Reform):
        def apply(self):
            self.modify_parameters(change_AR_param)
    
    return basic_rate_reform

def child_BI(value):
    class gross_income(Variable):
        value_type = float
        entity = Person
        label = u"Gross income, including benefits"
        definition_period = YEAR

        def formula(person, period, parameters):
            COMPONENTS = [
                "employment_income",
                "pension_income",
                "self_employment_income",
                "property_income",
                "savings_interest_income",
                "dividend_income",
                "miscellaneous_income",
                "benefits",
            ]
            return add(person, period, COMPONENTS) + person("is_child", period) * value * 52
    
    class child_BI(Reform):
        def apply(self):
            self.update_variable(gross_income)
    
    return child_BI

def create_reform(params):
    reforms = []
    if "abolish_PA" in params:
        reforms += [abolish_PA()]
    if "basic_rate" in params:
        reforms += [change_basic_rate(params["basic_rate"])]
    if "higher_rate" in params:
        reforms += [change_higher_rate(params["higher_rate"])]
    if "add_rate" in params:
        reforms += [change_add_rate(params["add_rate"])]
    if "child_BI" in params:
        reforms += [child_BI(params["child_BI"])]
    return reforms

@app.route("/reform", methods=["POST"])
def compute_reform():
    params = request.json
    reform = Microsimulation(create_reform(params))
    new_income = reform.calc("equiv_household_net_income", map_to="person")
    old_income = baseline.calc("equiv_household_net_income", map_to="person")
    gain = new_income - old_income
    net_cost = reform.calc("net_income").sum() - baseline.calc("net_income").sum()
    decile_plot = px.bar(gain.groupby(old_income.percentile_rank()).mean()).update_layout(
        title="Income effect by percentile",
        xaxis_title="Equivalised disposable income percentile",
        yaxis_title="Average income effect",
        yaxis_tickprefix="£",
        width=800,
        height=600,
        template="plotly_white",
        showlegend=False
    ).to_json()
    top_1_pct_share_effect = gain[old_income.percentile_rank() == 100].mean()
    top_10_pct_share_effect = gain[old_income.decile_rank() == 10].mean()
    median_effect = new_income.median() - old_income.median()
    return {"net_cost": gbp(net_cost), "decile_plot": json.loads(decile_plot), "1pct": top_1_pct_share_effect, "10pct": top_10_pct_share_effect, "median": median_effect}

@app.after_request
def after_request_func(response):
    origin = request.headers.get('Origin')
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Headers', 'x-csrf-token')
        response.headers.add('Access-Control-Allow-Methods',
                            'GET, POST, OPTIONS, PUT, PATCH, DELETE')
        if origin:
            response.headers.add('Access-Control-Allow-Origin', origin)
    else:
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        if origin:
            response.headers.add('Access-Control-Allow-Origin', origin)

    return response

if __name__ == "__main__":
    app.run()