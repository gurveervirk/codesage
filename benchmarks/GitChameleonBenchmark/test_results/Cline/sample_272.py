import plotly
def custom_chart_studio_usage() -> bool:
    try:
        import chart_studio.plotly as cs_plotly
        return hasattr(cs_plotly, "plot")
    except ImportError:
        return False
