# Complete using the following libraries and/or extra dependencies and their versions:
# problem statement: Define a function named custom_figure that accepts two lists representing x and y data. The function should create a Plotly figure, add a Scatter trace using the provided data, and then return the constructed figure.

# library: plotly
# version: 4.0.0
import plotly
import plotly.graph_objects as go


def custom_figure(x_data: list[int], y_data: list[int]) -> go.Figure:
    import plotly.