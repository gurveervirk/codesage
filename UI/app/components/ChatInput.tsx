import React, { useEffect } from "react";
import { useState } from "react";
import {
  TextField,
  Button,
  Paper,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  ListSubheader,
  SelectChangeEvent,
} from "@mui/material";
import SendIcon from "@mui/icons-material/Send";
import { useFetcher } from "@remix-run/react";
import { Alert, Snackbar } from "@mui/material";

export interface Model {
  id: string;
  name: string;
}

interface ChatInputProps {
  onSend: (message: string) => void;
  models: { [key: string]: Model[] };
}

export default function ChatInput({ onSend, models }: ChatInputProps) {
  const fetcher = useFetcher();
  const [input, setInput] = useState("");
  const [selectedModel, setSelectedModel] = useState(models['Current-Model'][0].id);
  const [snackbarOpen, setSnackbarOpen] = useState(false);
  const [snackbarMessage, setSnackbarMessage] = useState("");
  const [snackbarSeverity, setSnackbarSeverity] = useState<"success" | "error">("success");

  useEffect(() => {
    console.log(models);
  }, [models]);

  const handleSend = () => {
    if (!input.trim()) return;
    onSend(input);
    setInput("");
  }

  const handleModelChange = (event: SelectChangeEvent<string>) => {
    const [provider, modelId] = event.target.value.split("::");
    setSelectedModel(provider + "::" + modelId);
    fetcher.submit({ provider, modelId }, { method: "post", action: "/api/change_model" });
  };

  React.useEffect(() => {
    if (fetcher.data) {
      if ((fetcher.data as any).success) {
        setSnackbarMessage("Model changed successfully!");
        setSnackbarSeverity("success");
      } else {
        setSnackbarMessage(`Failed to change model: ${(fetcher.data as any).error || 'Unknown error'}`);
        setSnackbarSeverity("error");
      }
      setSnackbarOpen(true);
    }
  }, [fetcher.data]);

  const handleCloseSnackbar = () => {
    setSnackbarOpen(false);
  };

  return (
    <>
      <Snackbar
        open={snackbarOpen}
        autoHideDuration={5000}
        onClose={handleCloseSnackbar}
        anchorOrigin={{ vertical: "top", horizontal: "center" }}
      >
        <Alert onClose={handleCloseSnackbar} severity={snackbarSeverity} sx={{ width: '100%' }}>
          {snackbarMessage}
        </Alert>
      </Snackbar>
      <Paper
        elevation={2}
        sx={{
          p: 2,
          borderRadius: 2,
          display: "flex",
          gap: 2,
        }}
      >
        {models && (
          <FormControl sx={{ minWidth: 120 }}>
            <InputLabel id="model-select-label">Model</InputLabel>
            <Select
              labelId="model-select-label"
              id="model-select"
              value={selectedModel}
              label="Model"
              onChange={handleModelChange}
            >
              {Object.keys(models).reduce<React.ReactNode[]>((acc, provider) => {provider != 'Current-Model' &&
                acc.push(<ListSubheader key={provider}>{provider}</ListSubheader>);
                models[provider].forEach((model) => {
                  provider != 'Current-Model' &&
                  acc.push(
                    <MenuItem key={`${provider}::${model.id}`} value={`${provider}::${model.id}`}>
                      {model.name}
                    </MenuItem>
                  );
                });
                return acc;
              }, [])}
            </Select>
          </FormControl>

        )}
        <FormControl sx={{ width: "100%" }}>
          <TextField
            multiline
            fullWidth
            variant="outlined"
            label="Enter your query..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            sx={{
              maxHeight: 200,
              overflow: "auto",
              "& .MuiOutlinedInput-root": { borderRadius: "20px" },
            }}
          />
        </FormControl>
        <Button
          variant="contained"
          onClick={handleSend}
          sx={{ maxHeight: "50px", borderRadius: "20px", px: 3 }}
          endIcon={<SendIcon />}
        >
          Send
        </Button>
      </Paper>
    </>
  );
}
