import aerosandbox as asb
import aerosandbox.numpy as np

# Define the wing geometry
wing_span = 10  # meters
wing_chord = 1.5  # meters
wing_area = wing_span * wing_chord  # meters^2
wing_aspect_ratio = wing_span / wing_chord  # Non-dimensional

# Define the airfoil
airfoil_name = "naca0012"  # This is a symmetrical airfoil, good for demonstration purposes

# Define the flight conditions
velocity = 30  # m/s
altitude = 1000  # meters
density = asb.atmosphere.density(altitude)  # kg/m^3
dynamic_pressure = 0.5 * density * velocity**2  # Pa

# Create an AerodynamicSurfaces object
airplane = asb.Airplane(
    name="Simple Monoplane",
    wings=[
        asb.Wing(
            name="Main Wing",
            symmetric=True,  # Define as symmetrical
            xsecs=[
                asb.WingXSec(
                    airfoil=asb.Airfoil(name=airfoil_name),
                    chord=wing_chord,
                    twist=0, # Angle of attack of the wing
                )
            ],
            span=wing_span,
        )
    ],
)

# Run the aerodynamic analysis
op_point = asb.OperatingPoint(
    velocity=velocity,
    density=density,
    alpha=3,  # Angle of attack in degrees
    beta=0,
    p=0,
    q=0,
    r=0
)

# Solve with VLM - good for initial estimate and low to moderate angles of attack
aero_data = airplane.vlm_analysis(op_point)
#aero_data = airplane.avl_analysis(op_point) # Alternative solver, requires AVL installed

# Print the results
print("\nAnalysis Results (VLM):")
print(f"Lift Coefficient (CL): {aero_data['CL']}")
print(f"Drag Coefficient (CD): {aero_data['CD']}")
print(f"Lift (L): {aero_data['L']} N")
print(f"Drag (D): {aero_data['D']} N")
print(f"Lift-to-Drag Ratio (L/D): {aero_data['L/D']}")

# Estimate Parasite Drag from Wetted Area

# Estimate wetted area (very rough approximation for a monoplane)
wetted_area_wing = 2 * wing_area # Top and bottom surface
wetted_area_fuselage = 10 # estimate as 10 sq meters
wetted_area_total = wetted_area_wing + wetted_area_fuselage

# Skin friction coefficient (assuming turbulent flow) - This is VERY rough
reynolds_number = density * velocity * wing_chord / asb.atmosphere.viscosity(altitude)  # Reynolds number based on wing chord
Cf = 0.074 / (reynolds_number ** 0.2)  # Flat plate turbulent skin friction coefficient

# Estimate parasite drag coefficient based on wetted area and skin friction
CD_parasite = Cf * wetted_area_total / wing_area # Wing area is used as a reference area

print("\nParasite Drag Estimation (Wetted Area Method):")
print(f"Wetted Area (approximate): {wetted_area_total} m^2")
print(f"Reynolds Number: {reynolds_number}")
print(f"Skin Friction Coefficient: {Cf}")
print(f"CD_parasite: {CD_parasite}")
print(f"Total Drag Coefficient: {aero_data['CD'] + CD_parasite} (Including Parasite)")

# More advanced methods could include a lifting-line or panel code analysis
# with viscous drag estimation if those are available in aerosandbox,
# but they're typically not included in a basic library.

#  For more detailed and accurate results, consider:
# 1.  Adding a fuselage geometry to the airplane model.
# 2.  Using a more accurate wetted area calculation.
# 3.  Using a more accurate skin friction estimation method (e.g., based on local Reynolds number and surface roughness).
# 4.  Using experimental data or CFD simulations to calibrate the drag estimates.