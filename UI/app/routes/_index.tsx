import type { MetaFunction } from "@remix-run/node";
import { Box, Container, Typography, Button, Grid, Card, CardContent, useTheme } from "@mui/material";
import CodeIcon from "@mui/icons-material/Code";
import SchemaIcon from "@mui/icons-material/Schema";
import AutoFixHighIcon from "@mui/icons-material/AutoFixHigh";
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';
import { Link } from "@remix-run/react";

export const meta: MetaFunction = () => {
  return [
    { title: "CodeSage - Intelligent Code Analysis & Generation" },
    { name: "description", content: "CodeSage: Your AI-powered code analysis and generation platform" },
  ];
};

export default function Index() {
  const theme = useTheme();

  return (
    <Box
      sx={{
        minHeight: "100vh",
        background: `linear-gradient(145deg, ${theme.palette.background.default} 0%, ${theme.palette.background.paper} 100%)`,
        py: { xs: 4, md: 8 },
        fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
      }}
    >
      <Container maxWidth="lg">
        {/* Hero Section */}
        <Box
          sx={{
            textAlign: "center",
            mb: { xs: 8, md: 10 },
            mt: { xs: 4, md: 6 }
          }}
        >
          {/*<Box
            sx={{
              display: 'inline-flex',
              alignItems: 'center',
              bgcolor: 'rgba(25, 118, 210, 0.08)',
              px: 2.5,
              py: 1,
              borderRadius: 6,
              mb: 3
            }}
          >
            <Typography
              variant="subtitle2"
              sx={{
                color: 'primary.main',
                fontWeight: 600,
                letterSpacing: '0.03em',
              }}
            >
              BETA RELEASE NOW AVAILABLE
            </Typography>
          </Box>*/}

          <Typography
            variant="h1"
            component="h1"
            sx={{
              fontWeight: 800,
              mb: 3,
              fontSize: { xs: "2.5rem", sm: "3.5rem", md: "4rem" },
              letterSpacing: "-0.02em",
              lineHeight: 1.1,
              background: 'linear-gradient(45deg, #1976d2, #8a4fff)',
              backgroundClip: 'text',
              textFillColor: 'transparent',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
            }}
          >
            Coding, Amplified by Intelligence
          </Typography>

          <Typography
            variant="h5"
            sx={{
              color: "text.secondary",
              maxWidth: "750px",
              mx: "auto",
              mb: 6,
              fontWeight: 400,
              lineHeight: 1.5,
              fontSize: { xs: "1.1rem", md: "1.3rem" },
            }}
          >
            Your intelligent AI assistant that helps analyze, document, and generate code
            for modern software development teams
          </Typography>

          <Box
            sx={{
              display: "flex",
              gap: 3,
              justifyContent: "center",
              mb: 2,
              flexDirection: { xs: 'column', sm: 'row' },
              alignItems: 'center',
              maxWidth: '500px',
              mx: 'auto'
            }}
          >
            <Button
              component={Link}
              to="/login"
              variant="contained"
              size="large"
              endIcon={<ArrowForwardIcon />}
              sx={{
                px: 4,
                py: 1.75,
                borderRadius: 3,
                textTransform: "none",
                fontSize: "1.1rem",
                fontWeight: 600,
                letterSpacing: '0.02em',
                boxShadow: '0 8px 16px rgba(25, 118, 210, 0.2)',
                transition: 'all 0.3s ease',
                width: { xs: '100%', sm: 'auto' },
                '&:hover': {
                  transform: 'translateY(-3px)',
                  boxShadow: '0 12px 20px rgba(25, 118, 210, 0.25)',
                }
              }}
            >
              Get Started
            </Button>

            {/*<Button
              component={Link}
              to="/signup"
              variant="outlined"
              size="large"
              sx={{
                px: 4,
                py: 1.75,
                borderRadius: 3,
                textTransform: "none",
                fontSize: "1.1rem",
                fontWeight: 600,
                borderWidth: 2,
                letterSpacing: '0.02em',
                transition: 'all 0.3s ease',
                width: { xs: '100%', sm: 'auto' },
                '&:hover': {
                  borderWidth: 2,
                  background: 'rgba(25, 118, 210, 0.04)',
                }
              }}
            >
              Try Demo
            </Button>*/}
          </Box>

          {/* <Typography 
            variant="body2" 
            color="text.secondary"
            sx={{ 
              mt: 2,
              fontSize: '0.9rem',
              opacity: 0.8 
            }}
          >
            No credit card required. Free tier includes 100 requests per day.
          </Typography> */}
        </Box>

        {/* Features Section */}
        <Grid
          container
          spacing={4}
          sx={{
            mb: { xs: 8, md: 12 }
          }}
        >
          <Grid item xs={12} md={4}>
            <FeatureCard
              title="Code Analysis"
              description="Get detailed insights into your codebase structure, dependencies, and potential improvements."
              icon={<CodeIcon sx={{ fontSize: 40 }} />}
            />
          </Grid>
          <Grid item xs={12} md={4}>
            <FeatureCard
              title="Knowledge Graph"
              description="Visualize complex relationships between components in your codebase for better understanding."
              icon={<SchemaIcon sx={{ fontSize: 40 }} />}
            />
          </Grid>
          <Grid item xs={12} md={4}>
            <FeatureCard
              title="AI Generation"
              description="Generate boilerplate code, unit tests, and documentation with state-of-the-art AI models."
              icon={<AutoFixHighIcon sx={{ fontSize: 40 }} />}
            />
          </Grid>
        </Grid>

        {/* Footer CTA */}
        <Box
          sx={{
            textAlign: "center",
            p: 5,
            borderRadius: 4,
            background: 'linear-gradient(145deg, rgba(25, 118, 210, 0.05) 0%, rgba(138, 79, 255, 0.05) 100%)',
            border: '1px solid',
            borderColor: 'divider',
          }}
        >
          <Typography
            variant="h4"
            component="h2"
            sx={{
              fontWeight: 700,
              mb: 3,
              fontSize: { xs: "1.8rem", md: "2.3rem" },
              letterSpacing: "-0.01em",
            }}
          >
            Ready to transform your coding workflow?
          </Typography>

          {/* <Typography
            variant="body1"
            sx={{
              color: "text.secondary",
              maxWidth: "650px",
              mx: "auto",
              mb: 4,
              fontSize: "1.1rem",
            }}
          >
            Join thousands of developers who are already using CodeSage to work smarter, not harder.
          </Typography> */}

          <Link
            to="/login"
            style={{ textDecoration: 'none' }}
          >
            <Button
              variant="contained"
              size="large"
              sx={{
                px: 5,
                py: 1.75,
                borderRadius: 3,
                textTransform: "none",
                fontSize: "1.1rem",
                fontWeight: 600,
                boxShadow: '0 8px 16px rgba(25, 118, 210, 0.2)',
                transition: 'all 0.3s ease',
                '&:hover': {
                  transform: 'translateY(-3px)',
                  boxShadow: '0 12px 20px rgba(25, 118, 210, 0.25)',
                }
              }}
            >
              Start Using CodeSage
              <ArrowForwardIcon sx={{ ml: 1 }} />
            </Button>
          </Link>
        </Box>
      </Container>
    </Box>
  );
}

function FeatureCard({ title, description, icon }: { title: string; description: string; icon: React.ReactNode }) {
  return (
    <Card
      sx={{
        height: "100%",
        display: "flex",
        flexDirection: "column",
        transition: "transform 0.3s ease, box-shadow 0.3s ease",
        borderRadius: 3,
        border: '1px solid',
        borderColor: 'divider',
        overflow: 'visible',
        background: 'rgba(255, 255, 255, 0.8)',
        backdropFilter: 'blur(10px)',
        "&:hover": {
          transform: "translateY(-8px)",
          boxShadow: '0 16px 32px rgba(0, 0, 0, 0.1)',
        },
      }}
    >
      <CardContent sx={{ flexGrow: 1, p: 4 }}>
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            width: 80,
            height: 80,
            borderRadius: "50%",
            bgcolor: 'primary.main',
            color: 'white',
            mb: 3,
            transform: 'translateY(-20px)',
            mx: 'auto',
            boxShadow: '0 8px 16px rgba(25, 118, 210, 0.25)',
          }}
        >
          {icon}
        </Box>
        <Typography
          variant="h5"
          component="h3"
          gutterBottom
          sx={{
            fontWeight: 700,
            textAlign: 'center',
            mb: 2
          }}
        >
          {title}
        </Typography>
        <Typography
          variant="body1"
          color="text.secondary"
          sx={{
            textAlign: 'center',
            lineHeight: 1.6
          }}
        >
          {description}
        </Typography>
      </CardContent>
    </Card>
  );
}