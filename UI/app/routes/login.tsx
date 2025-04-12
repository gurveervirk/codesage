import React from "react";
import { useNavigate, Form, useActionData } from "@remix-run/react";
import { ActionFunctionArgs, redirect, json } from "@remix-run/node";
import { firebaseConfig } from "~/utils/firebase";
import { initializeApp, getApps } from "firebase/app";
import { getAuth, signInWithEmailAndPassword } from "firebase/auth";

// MUI Components
import { Box, Typography, Paper, Container,Grid, useTheme, useMediaQuery } from "@mui/material";

import { LoginDialog } from "~/components/LoginDialog";
import CodeIcon from '@mui/icons-material/Code';

// Initialize Firebase app only once
if (!getApps().length) {
  initializeApp(firebaseConfig);
}

// Action Handler for Login
export const action = async ({ request }: ActionFunctionArgs) => {
  try {
    const formData = await request.formData();
    const email = formData.get("email");
    const password = formData.get("password");
    const authType = formData.get("authType"); // 'email', 'google'

    if (typeof email !== "string" || typeof password !== "string" || typeof authType !== "string") {
      return Response.json({ message: "Invalid Form Data" }, { status: 400 });
    }

    if (authType === "email") {
      const auth = getAuth();
      const userCredential = await signInWithEmailAndPassword(auth, email, password);
      if(userCredential && userCredential.user){
           const idToken = await userCredential.user.getIdToken();

            // Set the cookie
            const cookieHeader = `idToken=${idToken}; Path=/; HttpOnly; Secure; Max-Age=3600; SameSite=Strict`;

            return redirect("/chat", {
              headers: {
                "Set-Cookie": cookieHeader,
              },
            });
      }
      else{
         return Response.json({ message: "Invalid Login" }, { status: 400 });
      }

    } else {
      // Handle Google OAuth here
      console.log("No provider setup for google oauth");
      return Response.json({ message: "Invalid Login" }, { status: 400 });
    }
  } catch (e: any) {
    console.error(e);
    return Response.json({ message: "Invalid Login" }, { status: 400 });
  }
};

export default function Login() {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('sm'));
  
  return (
    <Box 
      sx={{ 
        height: "100vh",
        overflow: "hidden",
        background: "linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%)"
      }}
    >
      <Grid container sx={{ height: "100%" }}>
        {/* Left panel with image - hidden on mobile */}
        <Grid 
          xs={0} 
          md={7} 
          lg={8}
          sx={{
            display: { xs: 'none', md: 'block' },
            position: 'relative',
            backgroundImage: "url(https://images.unsplash.com/photo-1566837945700-30057527ade0?q=80&w=2070)",
            backgroundRepeat: "no-repeat",
            backgroundSize: "cover",
            backgroundPosition: "center",
            boxShadow: "inset -10px 0px 20px rgba(0,0,0,0.1)",
            
            "&::before": {
              content: '""',
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              height: '100%',
              backgroundColor: 'rgba(0,0,0,0.4)',
              backdropFilter: 'blur(2px)',
            }
          }}
        >
          <Box 
            sx={{ 
              position: 'absolute', 
              bottom: 60, 
              left: 60, 
              maxWidth: '60%',
              zIndex: 1
            }}
          >
            <Typography 
              variant="h3" 
              sx={{ 
                color: 'white', 
                fontWeight: 700, 
                textShadow: '0px 2px 4px rgba(0,0,0,0.3)',
                mb: 2
              }}
            >
              CodeSage
            </Typography>
            <Typography 
              variant="h6" 
              sx={{ 
                color: 'rgba(255,255,255,0.9)', 
                fontWeight: 400,
                textShadow: '0px 1px 2px rgba(0,0,0,0.3)',
                lineHeight: 1.5,
              }}
            >
              Your AI-powered coding assistant. Get instant answers and explanations for your programming questions.
            </Typography>
          </Box>
        </Grid>
        
        {/* Right panel with login form */}
        <Grid 
          xs={12} 
          md={5} 
          lg={4} 
          sx={{ 
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
            p: { xs: 2, sm: 4, md: 6 },
          }}
        >
          <Paper 
            elevation={isMobile ? 0 : 6} 
            sx={{ 
              p: { xs: 3, sm: 4 },
              borderRadius: 2,
              backdropFilter: 'blur(10px)',
              backgroundColor: 'rgba(255, 255, 255, 0.95)',
              maxWidth: 500,
              mx: 'auto',
              width: '100%',
              boxShadow: isMobile ? 'none' : '0 8px 32px rgba(0, 0, 0, 0.12)'
            }}
          >
            <Box
              sx={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
              }}
            >
              <Box 
                sx={{ 
                  display: 'flex', 
                  alignItems: 'center', 
                  mb: 4, 
                  gap: 1.5 
                }}
              >
                <CodeIcon 
                  sx={{ 
                    color: 'primary.main', 
                    fontSize: { xs: 32, sm: 40 } 
                  }} 
                />
                <Typography 
                  component="h1" 
                  variant={isMobile ? "h5" : "h4"} 
                  sx={{ 
                    fontWeight: 700, 
                    color: 'text.primary',
                    letterSpacing: '-0.01em'
                  }}
                >
                  CodeSage
                </Typography>
              </Box>
              
              <Typography 
                variant="body1" 
                align="center" 
                sx={{ 
                  mb: 3, 
                  color: 'text.secondary', 
                  maxWidth: 400
                }}
              >
                Sign in to your account to continue your coding journey
              </Typography>
              
              <LoginDialog />
              
              <Typography 
                variant="caption" 
                sx={{ 
                  mt: 4, 
                  color: 'text.disabled', 
                  textAlign: 'center' 
                }}
              >
                By signing in, you agree to our Terms of Service and Privacy Policy
              </Typography>
            </Box>
          </Paper>
        </Grid>
      </Grid>
    </Box>
  );
}