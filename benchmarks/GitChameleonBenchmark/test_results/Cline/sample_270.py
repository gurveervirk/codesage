import plotly
import plotly.graph_objects as go
from plotly.subplots import make_subplots

def custom_make_subplots(rows: int, cols: int) -> go.Figure:
    fig = make_subplots(rows=rows, cols=cols)
    return fig
