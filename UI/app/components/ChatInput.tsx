import React, { useEffect, useState, useRef } from "react";
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
  IconButton,
  Box,
  Tooltip,
  useTheme,
  useMediaQuery,
  InputAdornment,
  Zoom,
  Fade,
} from "@mui/material";
import SendIcon from "@mui/icons-material/Send";
import SettingsIcon from "@mui/icons-material/Settings";
import KeyboardArrowUpIcon from "@mui/icons-material/KeyboardArrowUp";
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
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [snackbarOpen, setSnackbarOpen] = useState(false);
  const [snackbarMessage, setSnackbarMessage] = useState("");
  const [snackbarSeverity, setSnackbarSeverity] = useState<"success" | "error">("success");
  const [isExpanded, setIsExpanded] = useState(false);
  const textFieldRef = useRef<HTMLInputElement>(null);
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('sm'));
  const isSmallScreen = useMediaQuery(theme.breakpoints.down('md'));

  useEffect(() => {
    if (models && models['Current-Model'] && models['Current-Model'].length > 0) {
      setSelectedModel(models['Current-Model'][0].id);
    }
  }, [models]);

  // Auto-focus the input field when component mounts
  useEffect(() => {
    if (textFieldRef.current) {
      textFieldRef.current.focus();
    }
  }, []);

  const handleSend = () => {
    if (!input.trim()) return;
    onSend(input);
    setInput("");
    setIsExpanded(false);
    // Re-focus the input field
    if (textFieldRef.current) {
      textFieldRef.current.focus();
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // Send on Enter (but not with Shift+Enter, which creates a new line)
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const handleInputFocus = () => {
    setIsExpanded(true);
  };

  const handleInputBlur = (e: React.FocusEvent) => {
    // Only collapse if clicking outside the component
    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
      if (!input.trim()) {
        setIsExpanded(false);
      }
    }
  };

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

  const getCurrentModelName = () => {
    if (!models || !selectedModel) return "Select Model";
    
    const [provider, modelId] = selectedModel.split("::");
    const providerModels = models[provider];
    if (!providerModels) return "Select Model";
    
    const model = providerModels.find(m => m.id === modelId);
    return model ? model.name : "Select Model";
  };

  return (
    <>
      <Snackbar
        open={snackbarOpen}
        autoHideDuration={5000}
        onClose={handleCloseSnackbar}
        anchorOrigin={{ vertical: "top", horizontal: "center" }}
      >
        <Alert 
          onClose={handleCloseSnackbar} 
          severity={snackbarSeverity} 
          sx={{ 
            width: '100%',
            boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
            borderRadius: '8px'
          }}
        >
          {snackbarMessage}
        </Alert>
      </Snackbar>

      <Box 
        mx="auto" 
        maxWidth="1000px" 
        width="100%" 
        px={{ xs: 1, sm: 2 }} 
        mb={2}
        sx={{
          position: 'relative',
          zIndex: 10,
        }}
      >
        <Paper
          elevation={3}
          sx={{
            p: { xs: 1.5, sm: 2 },
            borderRadius: isExpanded ? 3 : 6,
            display: "flex",
            gap: 1.5,
            flexDirection: isSmallScreen && isExpanded ? 'column' : 'row',
            alignItems: "center",
            boxShadow: isExpanded 
              ? '0 8px 32px rgba(0,0,0,0.15)' 
              : '0 4px 20px rgba(0,0,0,0.1)',
            border: '1px solid',
            borderColor: isExpanded ? 'primary.light' : 'divider',
            bgcolor: theme.palette.background.paper,
            position: 'relative',
            transition: 'all 0.3s ease',
            transform: isExpanded ? 'translateY(-4px)' : 'none',
          }}
          onFocus={handleInputFocus}
          onBlur={handleInputBlur}
        >
          {/* Model selector - condensed on mobile */}
          {models && (
            <>
              <Fade in={isExpanded || !isMobile}>
                <FormControl 
                  size="small" 
                  sx={{ 
                    minWidth: 150,
                    display: isMobile && !isExpanded ? 'none' : 'block',
                    '& .MuiOutlinedInput-root': {
                      borderRadius: '10px',
                      transition: 'all 0.2s ease',
                      border: '1px solid',
                      borderColor: 'divider',
                      '&:hover': {
                        borderColor: 'primary.main',
                      }
                    }
                  }}
                >
                  <InputLabel id="model-select-label" sx={{ bgcolor: isExpanded ? 'background.paper' : 'transparent', px: 1 }}>Model</InputLabel>
                  <Select
                    labelId="model-select-label"
                    id="model-select"
                    value={selectedModel}
                    label="Model"
                    onChange={handleModelChange}
                    MenuProps={{
                      PaperProps: {
                        elevation: 3,
                        sx: {
                          borderRadius: 2,
                          mt: 1,
                          boxShadow: '0 8px 24px rgba(0,0,0,0.15)',
                        }
                      }
                    }}
                  >
                    {Object.keys(models).reduce<React.ReactNode[]>((acc, provider) => {
                      provider !== 'Current-Model' && acc.push(
                        <ListSubheader 
                          key={provider}
                          sx={{
                            bgcolor: theme.palette.mode === 'light' ? 'background.default' : 'background.paper',
                            color: 'primary.main',
                            fontWeight: 600,
                            lineHeight: '36px',
                          }}
                        >
                          {provider}
                        </ListSubheader>
                      );
                      models[provider].forEach((model) => {
                        provider !== 'Current-Model' && acc.push(
                          <MenuItem 
                            key={`${provider}::${model.id}`} 
                            value={`${provider}::${model.id}`}
                            sx={{
                              py: 1,
                              '&:hover': {
                                bgcolor: 'action.hover',
                              },
                              '&.Mui-selected': {
                                bgcolor: 'primary.lighter',
                                fontWeight: 500,
                                '&:hover': {
                                  bgcolor: 'primary.lighter',
                                }
                              }
                            }}
                          >
                            {model.name}
                          </MenuItem>
                        );
                      });
                      return acc;
                    }, [])}
                  </Select>
                </FormControl>
              </Fade>

              {isMobile && !isExpanded && (
                <Tooltip title="Change AI Model" arrow>
                  <IconButton 
                    size="small" 
                    onClick={handleInputFocus}
                    sx={{
                      color: 'primary.main',
                      bgcolor: 'action.hover',
                      '&:hover': {
                        bgcolor: 'action.selected',
                      },
                      height: 36,
                      width: 36,
                    }}
                  >
                    <SettingsIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              )}
            </>
          )}

          {/* Message input */}
          <FormControl sx={{ width: "100%" }}>
            <TextField
              multiline
              inputRef={textFieldRef}
              maxRows={isExpanded ? 6 : 1}
              fullWidth
              variant="outlined"
              placeholder={isExpanded ? "Type your message..." : "Ask CodeSage something..."}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              onFocus={handleInputFocus}
              sx={{
                '& .MuiOutlinedInput-root': {
                  borderRadius: '12px',
                  py: isExpanded ? 1 : 0.5,
                  backgroundColor: theme.palette.mode === 'light' ? 'rgba(245,247,250,0.6)' : 'rgba(30,35,45,0.6)',
                  transition: 'all 0.2s ease',
                  '&.Mui-focused': {
                    boxShadow: '0 0 0 2px rgba(25, 118, 210, 0.2)',
                    bgcolor: theme.palette.mode === 'light' ? 'rgba(245,247,250,0.9)' : 'rgba(30,35,45,0.9)',
                  },
                }
              }}
              InputProps={{
                endAdornment: (
                  <InputAdornment position="end">
                    {isExpanded && isMobile && (
                      <IconButton 
                        onClick={() => setIsExpanded(false)}
                        edge="end"
                        sx={{
                          color: 'text.secondary',
                          mr: 0.5,
                          transition: 'all 0.2s ease',
                        }}
                      >
                        <KeyboardArrowUpIcon />
                      </IconButton>
                    )}
                    <Zoom in={Boolean(input.trim())}>
                      <IconButton 
                        onClick={handleSend} 
                        disabled={!input.trim()}
                        sx={{
                          bgcolor: input.trim() ? 'primary.main' : 'action.disabledBackground',
                          color: input.trim() ? 'white' : 'text.disabled',
                          borderRadius: '10px',
                          width: 36,
                          height: 36,
                          '&:hover': {
                            bgcolor: input.trim() ? 'primary.dark' : 'action.disabledBackground',
                            transform: 'scale(1.05)',
                          },
                          transition: 'all 0.2s ease',
                          mr: 0.5,
                        }}
                      >
                        <SendIcon fontSize="small" />
                      </IconButton>
                    </Zoom>
                  </InputAdornment>
                )
              }}
            />
          </FormControl>
          
          {/* Send button - hidden on mobile (moved inside TextField) */}
          {!isMobile && (
            <Zoom in={Boolean(input.trim())}>
              <Button
                variant="contained"
                onClick={handleSend}
                disabled={!input.trim()}
                sx={{
                  height: '46px',
                  minWidth: '100px',
                  borderRadius: '10px',
                  fontWeight: 500,
                  boxShadow: '0 4px 10px rgba(25, 118, 210, 0.25)',
                  transition: 'all 0.2s ease',
                  flexShrink: 0,
                  '&:hover': {
                    transform: 'translateY(-2px)',
                    boxShadow: '0 6px 15px rgba(25, 118, 210, 0.35)',
                  },
                  opacity: input.trim() ? 1 : 0,
                }}
                endIcon={<SendIcon />}
              >
                Send
              </Button>
            </Zoom>
          )}
        </Paper>
      </Box>
    </>
  );
}
