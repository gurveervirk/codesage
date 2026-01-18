import plotly.graph_objects as go

def custom_fig(x_data: list[int], y_data: list[int], color_set: str) -> go.Figure:
    fig = go.Figure(
        data=[
            go.Scatter(
                x=x_data,
                y=y_data,
                mode="markers",
                error_y={"type": "data", "array": [1]*len(y_data), "color": color_set}
            )
        ]
    )
    return fig
