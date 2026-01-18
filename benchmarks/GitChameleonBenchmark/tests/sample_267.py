# Complete using the following libraries and/or extra dependencies and their versions:
# problem statement: Create a custom function named custom_fig that add an annotation to a Plotly figure at position x=0.5 and y=0.5 with the text “Example Annotation”. Ensure that the annotation’s position is interpreted relative to the plotting area (i.e., using the “paper” coordinate system) and return the object.
# library: plotly
# version: 5.8.0
import plotly.graph_objects as go

def custom_fig(fig: go.Figure) -> go.Figure:
    return 