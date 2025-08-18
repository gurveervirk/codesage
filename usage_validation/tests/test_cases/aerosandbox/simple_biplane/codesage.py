import aerosandbox.geometry as ag

# Define parameters for the biplane wings
span = 10.0       # Total wingspan for each wing (symmetric)
chord = 1.0       # Chord length for the rectangular wings
separation = 2.0  # Vertical separation between the lower and upper wing (z-axis)
stagger = 0.5     # Horizontal stagger (x-axis offset) of the upper wing relative to the lower wing
airfoil = ag.Airfoil("naca0012") # Define a simple airfoil shape

# --- Create the Lower Wing ---
# Define the cross-sections for the lower wing.
# For a rectangular wing, we need two cross-sections: root and tip.
# xyz_le is the [x, y, z] coordinate of the leading edge.
lower_wing_xsecs = [
    ag.WingXSec(
        xyz_le=[0, 0, 0],      # Root at the origin [x, y, z]
        chord=chord,
        airfoil=airfoil
    ),
    ag.WingXSec(
        xyz_le=[0, span / 2, 0], # Tip at half span in y, same x and z as root
        chord=chord,
        airfoil=airfoil
    )
]

# Create the Wing object for the lower wing.
# symmetric=True means the defined half-span is mirrored across the XZ plane (y=0).
lower_wing = ag.Wing(
    name="Lower Wing",
    xsecs=lower_wing_xsecs,
    symmetric=True
)

# --- Create the Upper Wing ---
# Define the cross-sections for the upper wing.
# These are similar to the lower wing but offset in x (stagger) and z (separation).
upper_wing_xsecs = [
    ag.WingXSec(
        xyz_le=[stagger, 0, separation],      # Root offset by stagger in x and separation in z
        chord=chord,
        airfoil=airfoil
    ),
    ag.WingXSec(
        xyz_le=[stagger, span / 2, separation], # Tip offset by stagger in x and separation in z, half span in y
        chord=chord,
        airfoil=airfoil
    )
]

# Create the Wing object for the upper wing, also symmetric.
upper_wing = ag.Wing(
    name="Upper Wing",
    xsecs=upper_wing_xsecs,
    symmetric=True
)

# --- Create the Airplane ---
# Create the Airplane object, which is a container for the wings (and other components).
biplane = ag.Airplane(
    name="Simple Biplane",
    wings=[lower_wing, upper_wing] # Add both created wings to the airplane
)

print(biplane)