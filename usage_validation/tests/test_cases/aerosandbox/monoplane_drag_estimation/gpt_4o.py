import aerosandbox as asb
import aerosandbox.numpy as np

# Define the aircraft
wing = asb.Wing(
    name="Main Wing",
    xsecs=[
        asb.WingXSec(
            xyz_le=[0, 0, 0],  # Root leading edge
            chord=1.5,
            twist=2,
            airfoil=asb.Airfoil("naca2412")
        ),
        asb.WingXSec(
            xyz_le=[3, 6, 0],  # Tip leading edge
            chord=0.5,
            twist=-1,
            airfoil=asb.Airfoil("naca2412")
        )
    ],
    symmetric=True
)

airplane = asb.Airplane(
    wings=[wing],
    reference_area=wing.area(),  # Automatically calculate reference area
    reference_span=wing.span(),
    reference_chord=wing.mean_aerodynamic_chord(),
)

# Define flight conditions
operating_point = asb.OperatingPoint(
    velocity=50,     # m/s
    alpha=5,         # degrees
    beta=0,
    altitude=0       # Sea level
)

# Set up the aerodynamic analysis
aero_analysis = asb.aerodynamics.aero_3D.VortexLatticeMethod(
    airplane=airplane,
    operating_point=operating_point
)

# Run the analysis
aero_data = aero_analysis.run()

# Output drag estimation
print(f"Drag Coefficient (CD): {aero_data['CD']:.4f}")
print(f"Lift Coefficient (CL): {aero_data['CL']:.4f}")
print(f"Lift-to-Drag Ratio (L/D): {aero_data['CL']/aero_data['CD']:.2f}")
