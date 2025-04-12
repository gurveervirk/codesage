// app/components/LoginDialog.jsx
import React, { useState } from "react";
import { Form, Link } from "@remix-run/react";

// MUI Components
import {Button, TextField, Box} from "@mui/material";

export function LoginDialog() {
  const [authType, setAuthType] = useState("email");

  return (
    <Box component="div" mt={1}>
      <Form method="post">
        {authType === "email" ? (
          <>
            <TextField
              margin="normal"
              required
              fullWidth
              id="email"
              placeholder="Email Address"
              name="email"
              autoComplete="email"
              autoFocus
            />
            <TextField
              margin="normal"
              required
              fullWidth
              name="password"
              placeholder="Password"
              type="password"
              id="password"
              autoComplete="current-password"
            />
            <input type="hidden" name="authType" value="email" />
          </>
        ) : null}

        <Button
          type="submit"
          fullWidth
          variant="contained"
          sx={{ mt: 3, mb: 2 }}
        >
          {authType === "email" ? "Login" : "Continue with Google"}
        </Button>
      </Form>

      {authType === "email" ? (
        <Button onClick={() => setAuthType("google")}>Login with Google</Button>
      ) : (
        <Button onClick={() => setAuthType("email")}>Login with Email</Button>
      )}
      <Link to="/signup">
        {" "}
        Don't have an account? Sign Up
      </Link>
    </Box>
  );
}