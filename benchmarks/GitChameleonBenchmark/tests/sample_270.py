# Complete using the following libraries and/or extra dependencies and their versions:
# problem statement: Define a function named custom_make_subplots that takes two parameters, rows and cols, and returns a subplot layout created with the specified number of rows and columns.

# library: plotly
# version: 4.0.0
import plotly
import plotly.graph_objects as go

def custom_make_subplots(rows: int, cols: int) -> go.Figure:
    return 