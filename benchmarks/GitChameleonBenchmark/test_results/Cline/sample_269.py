import plotly.graph_objects as go

def custom_fig(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        scene_camera={
            "eye": {"x": 1.25, "y": 1.25, "z": 1.25}
        }
    )
    return fig
