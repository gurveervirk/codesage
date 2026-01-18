import plotly
def custom_api_usage() -> str:
    try:
        import chart_studio.api as cs_api
        return cs_api.__name__
    except ImportError:
        return ""
