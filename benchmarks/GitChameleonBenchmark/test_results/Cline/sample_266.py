import plotly.graph_objects as go

def custom_fig(x_data: list[str], y_data: list[int]) -> go.Figure:
    fig = go.Figure(data=[go.Bar(x=x_data, y=y_data)])
    return fig
