# Complete using the following libraries and/or extra dependencies and their versions:
# problem statement: Create a custom function named custom_fig that that draw a vertical bar chart figure by using given x_data and y_data and return the object.
# library: plotly
# version: 4.8.0
import plotly.graph_objects as go


def custom_fig(x_data: list[str], y_data: list[int]) -> go.Figure:
    return 