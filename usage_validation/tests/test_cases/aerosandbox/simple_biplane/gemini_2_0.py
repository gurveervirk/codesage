import aerosandbox as asb
import aerosandbox.numpy as np
import matplotlib.pyplot as plt

# Define airfoil
airfoil = asb.Airfoil("naca4412")

# Define geometry
wing_upper = asb.Wing(
    name="Upper Wing",
    symmetric=False,
    x_le=0,
    y_le=0,
    z_le=5,  # Shift the upper wing up
    chord=2,
    span=10,
    airfoil=airfoil
)

wing_lower = asb.Wing(
    name="Lower Wing",
    symmetric=False,
    x_le=0,
    y_le=0,
    z_le=0,  # Bottom wing is at z=0
    chord=2,
    span=10,
    airfoil=airfoil
)

# Define fuselage (optional but good for visualization)
fuselage = asb.Fuselage(
    name="Fuselage",
    width=0.5,
    length=5,
    height=0.5,
    x_le=0
)

# Combine into an airplane
airplane = asb.Airplane(
    name="Biplane",
    wings=[wing_upper, wing_lower],
    fuselages=[fuselage]
)


# Run a simple lifting line analysis
op_point = asb.OperatingPoint(
    velocity=10,
    alpha=5,
    beta=0,
    rho=1.225
)

aero_data = airplane.aero_forces_and_moments(
    op_point=op_point,
    method="avl" # or "vlm" or "LLT" (LLT is fast but less accurate)
)

print(aero_data)

# Visualize the geometry
airplane.draw(show=False) # Use show=False if you want to customize the plot
plt.title("Biplane Geometry")
plt.xlabel("x")
plt.ylabel("y")
plt.gca().set_aspect('equal') # Important for accurate representation
plt.show()


# Visualize the aerodynamic loads (requires VLM or LLT)
if aero_data["CL"] is not None and aero_data["CL"] > 0.0:  # Check if a solution was found
    airplane.draw(
        show=False,
        draw_positive_spanwise_direction=True,
        draw_negative_spanwise_direction=True,
        airfoil_shape_kwargs=dict(
            alpha=0.0,
            outline=None
        ),
        wing_kwargs=dict(
            color='k',
        )
    )

    # Draw loads on the upper wing
    asb.draw_wireframe(
        Points=wing_upper.xyz_le + wing_upper.xyz_te,
        edges=wing_upper.mesh_do_edges,
        color="k",
        alpha=0.4
    )
    # Draw loads on the lower wing
    asb.draw_wireframe(
        Points=wing_lower.xyz_le + wing_lower.xyz_te,
        edges=wing_lower.mesh_do_edges,
        color="k",
        alpha=0.4
    )

    # Plot downwash
    x = aero_data['Downwash_Grid']['x']
    y = aero_data['Downwash_Grid']['y']
    z = aero_data['Downwash_Grid']['z']
    Vx = aero_data['Downwash_Grid']['Vx']
    Vy = aero_data['Downwash_Grid']['Vy']
    Vz = aero_data['Downwash_Grid']['Vz']

    import matplotlib.colors as mcolors

    norm = mcolors.Normalize(vmin=-np.max(np.abs(Vz)), vmax=np.max(np.abs(Vz)))
    cmap = 'RdBu_r'

    asb.draw_quiver(
        x, y, z,
        Vx, Vy, Vz,
        vector_scale=0.2,
        vector_lift=0.1,
        colors=plt.cm.get_cmap(cmap)(norm(Vz)),
    )

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    plt.colorbar(sm)

    plt.title("Biplane Downwash")
    plt.xlabel("x")
    plt.ylabel("y")
    plt.gca().set_aspect('equal')
    plt.show()
else:
    print("No valid aerodynamic solution found.  Check AoA, airspeed, and wing geometry.")