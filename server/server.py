from flask import Blueprint, jsonify
# render_template, json, request, current_app

from . import stats as req_stats

main = Blueprint('main', __name__)


@main.before_app_first_request
def before_first_request():
    # for future usages
    pass


@main.before_app_request
def before_request():
    """Update requests per second stats."""
    req_stats.add_request()


@main.route('/')
def index():
    """Serve client-side application"""
    # return render_template('index.html')
    return "Hello World"


@main.route('/stats', methods=['GET'])
def get_stats():
    return jsonify({'requests_per_second': req_stats.requests_per_second()})