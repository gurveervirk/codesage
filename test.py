import aerosandbox as asb
import aerosandbox.numpy as np

# Define the geometry of the biplane
wing = asb.Wing(
    symmetric=True,
    xsecs=[
        asb.Airfoil("naca4412").translate(xyz_nondim=[0, 0, 0]),
        asb.Airfoil("naca4412").translate(xyz_nondim=[0.02, 0.5, 0]) # Add a slight stagger
    ],
    chord=1,
    span=10
)

horizontal_stabilizer = asb.Wing(
    symmetric=True,
    xsecs=[
        asb.Airfoil("naca0012").translate(xyz_nondim=[0, 0, 0]),
        asb.Airfoil("naca0012").translate(xyz_nondim=[0, 0.5, 0])  #No stagger
    ],
    chord=0.7,
    span=8
)

airplane = asb.Airplane(
    wings=[wing, horizontal_stabilizer.translate(xyz=[4, 0, -2])]
)

# Define the operating point
op_point = asb.OperatingPoint(
    velocity=30,  # m/s
    alpha=5,  # degrees
    beta=0,  # degrees
    atmosphere=asb.Atmosphere(altitude=0) # Sea level
)

# Run the Vortex Lattice Method analysis
analysis = asb.VortexLatticeMethod(
    airplane=airplane,
    op_point=op_point,
    spanwise_resolution=16, # Increase for accuracy
    chordwise_resolution=8  # Increase for accuracy
)

aero_data = analysis.run()

# Print the results
print(aero_data)

# Access the drag coefficient
CD = aero_data["CD"]
print(f"Drag Coefficient: {CD}")