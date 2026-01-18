# Complete using the following libraries and/or extra dependencies and their versions:
# problem statement: Create a custom function named custom_fig that create a 3D scatter plot using Plotly and update its camera settings. Set the camera’s eye position to x=1.25, y=1.25, z=1.25 and return the object.
# library: plotly
# version: 5.10.0
import plotly.graph_objects as go

def custom_fig(fig: go.Figure) -> go.Figure:
    return 