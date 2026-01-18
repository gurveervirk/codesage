# Complete using the following libraries and/or extra dependencies and their versions:
# problem statement: Create a custom function named custom_fig that that ceate a scatter plot with error bars using Plotly. Set the error bar color using an RGBA value (given color_set) that includes an alpha channel for opacity and return the object.
# library: plotly
# version: 5.10.0
import plotly.graph_objects as go

def custom_fig(x_data: list[int], y_data: list[int], color_set: str) -> go.Figure:
    return 