// app/routes/login.tsx
import React from "react";
import { useNavigate, Form, useActionData } from "@remix-run/react";
import { ActionFunctionArgs, redirect, json } from "@remix-run/node";
import { firebaseConfig } from "~/utils/firebase";
import { initializeApp, getApps } from "firebase/app";
import { getAuth, signInWithEmailAndPassword } from "firebase/auth";

// MUI Components
import {Box,Typography,Grid2} from "@mui/material"
import { LoginDialog } from "~/components/LoginDialog";

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
  return (
    <Grid2 container component="main" sx={{ height: "100vh" }}>
      <Grid2
        size = {{ xs: 12, sm: 4, md: 7 }}
        sx={{
          backgroundImage: "url(https://source.unsplash.com/random)", // Replace with your image
          backgroundRepeat: "no-repeat",
          backgroundColor: (t) =>
            t.palette.mode === "light"
              ? t.palette.grey[50]
              : t.palette.grey[900],
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      />
      <Grid2 size = {{ xs: 12, sm: 8, md: 5 }} sx={{ boxShadow: '0px 2px 4px rgba(0,0,0,0.2)' }}>
        <Box
          sx={{
            my: 8,
            mx: 4,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
          }}
        >
          <Typography component="h1" variant="h5">
            Sign in
          </Typography>
          <LoginDialog />
        </Box>
      </Grid2>
    </Grid2>
  );
}