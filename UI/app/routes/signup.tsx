import React from "react";
import { useNavigate, Form, useActionData } from "@remix-run/react";
import { ActionFunctionArgs, redirect, json } from "@remix-run/node";
import { firebaseConfig } from "~/utils/firebase";
import { initializeApp, getApps } from "firebase/app";
import { getAuth, createUserWithEmailAndPassword } from "firebase/auth";
import {
  Box,
  Container,
  Typography,
  TextField,
  Button,
  Alert,
  Paper,
  useTheme,
} from "@mui/material";
import { Link } from "@remix-run/react";

// Initialize Firebase app only once
if (!getApps().length) {
  initializeApp(firebaseConfig);
}

// Action Handler for Signup
export const action = async ({ request }: ActionFunctionArgs) => {
  try {
    const formData = await request.formData();
    const email = formData.get("email");
    const password = formData.get("password");
    const confirmPassword = formData.get("confirmPassword");

    if (typeof email !== "string" || typeof password !== "string" || typeof confirmPassword !== "string") {
      return json({ error: "Invalid form data" }, { status: 400 });
    }

    if (password !== confirmPassword) {
      return json({ error: "Passwords do not match" }, { status: 400 });
    }

    const auth = getAuth();
    const userCredential = await createUserWithEmailAndPassword(auth, email, password);
    
    if (userCredential && userCredential.user) {
      const idToken = await userCredential.user.getIdToken();
      
      // Set the cookie
      const cookieHeader = `idToken=${idToken}; Path=/; HttpOnly; Secure; Max-Age=3600; SameSite=Strict`;
      
      return redirect("/chat", {
        headers: {
          "Set-Cookie": cookieHeader,
        },
      });
    }
    
    return json({ error: "Failed to create account" }, { status: 500 });
  } catch (error: any) {
    return json({ error: error.message }, { status: 400 });
  }
};

export default function Signup() {
  const actionData = useActionData<typeof action>();
  const navigate = useNavigate();
  const theme = useTheme();

  return (
    <Box
      sx={{
        minHeight: "100vh",
        background: `linear-gradient(to bottom, ${theme.palette.background.default}, ${theme.palette.background.paper})`,
        display: "flex",
        alignItems: "center",
        py: 4,
      }}
    >
      <Container maxWidth="sm">
        <Paper
          elevation={3}
          sx={{
            p: { xs: 3, sm: 4 },
            borderRadius: 2,
          }}
        >
          <Box sx={{ textAlign: "center", mb: 4 }}>
            <Typography variant="h4" component="h1" gutterBottom>
              Create your account
            </Typography>
            <Typography variant="body1" color="text.secondary">
              Join CodeSage and start analyzing your codebase
            </Typography>
          </Box>

          <Form method="post">
            <Box sx={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {actionData?.error && (
                <Alert severity="error" sx={{ mb: 2 }}>
                  {actionData.error}
                </Alert>
              )}

              <TextField
                required
                fullWidth
                id="email"
                name="email"
                placeholder="Email address"
                type="email"
                autoComplete="email"
                variant="outlined"
              />

              <TextField
                required
                fullWidth
                id="password"
                name="password"
                placeholder="Password"
                type="password"
                autoComplete="new-password"
                variant="outlined"
              />

              <TextField
                required
                fullWidth
                id="confirmPassword"
                name="confirmPassword"
                placeholder="Confirm Password"
                type="password"
                autoComplete="new-password"
                variant="outlined"
              />

              <Button
                type="submit"
                variant="contained"
                size="large"
                fullWidth
                sx={{
                  py: 1.5,
                  borderRadius: 2,
                  textTransform: "none",
                  fontSize: "1.1rem",
                }}
              >
                Create Account
              </Button>
            </Box>
          </Form>

          <Box sx={{ mt: 4, textAlign: "center" }}>
            <Typography variant="body2" color="text.secondary">
              Already have an account?{" "}
              <Button
                component={Link}
                to="/login"
                sx={{
                  textTransform: "none",
                  p: 0,
                  minWidth: 0,
                  verticalAlign: "baseline",
                }}
              >
                Sign in
              </Button>
            </Typography>
          </Box>
        </Paper>
      </Container>
    </Box>
  );
} 