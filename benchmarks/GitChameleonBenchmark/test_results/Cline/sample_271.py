import plotly
import plotly.graph_objects as go

def custom_figure(x_data: list[int], y_data: list[int]) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x_data, y=y_data))
    return fig
