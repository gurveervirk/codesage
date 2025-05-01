// app/routes/chat.tsx
import { useState, useRef, useEffect } from "react";
import { Box, IconButton, Snackbar, Alert, useTheme, Paper, Typography, Fade } from "@mui/material";
import MenuIcon from "@mui/icons-material/Menu";
import CloseIcon from "@mui/icons-material/Close";
import Sidebar from "~/components/Sidebar";
import UploadModule from "~/components/UploadModule";
import {MessageContainer, MessageInterface} from "~/components/MessageContainer";
import ChatInput from "~/components/ChatInput";
import { useLoaderData } from "@remix-run/react";
import { loader as available_models_loader } from "~/loaders/available_models";
export { available_models_loader as loader };
import { Model } from "~/components/ChatInput";

// Helper function to generate stable IDs that don't cause hydration mismatches
let messageCounter = 0;
const generateStableId = (prefix: string) => `${prefix}-${messageCounter++}`;

export default function Chat() {
  const models = useLoaderData<{ [key: string]: Model[] }>();
  const [messages, setMessages] = useState<MessageInterface[]>([]);
  const [loading, setLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [currentContextId, setCurrentContextId] = useState<string | null>(null);
  const [notification, setNotification] = useState<{
    open: boolean,
    message: string,
    severity: "success" | "error" | "info" | "warning"
  }>({
    open: false,
    message: "",
    severity: "info"
  });
  
  const eventSourceRef = useRef<EventSource | null>(null);
  const theme = useTheme();

  // Reset message counter on client side after hydration
  useEffect(() => {
    messageCounter = 0;
  }, []);

  const handleSendMessage = async (message: string) => {
    // 1. Add user message to the state immediately with a stable ID
    const newMessage: MessageInterface = { 
      text: message, 
      sender: "user", 
      id: generateStableId('user-msg')
    };
    setMessages((prevMessages) => [...prevMessages, newMessage]);
    setLoading(true);

    // 2. Close existing EventSource if it exists
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    // 3. POST to chat-workflow endpoint and handle streaming response
    try {
      const response = await fetch("/api/chat-workflow", {
        method: "POST",
        body: JSON.stringify({ prompt: message }),
        headers: {
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        const errorData = await response.json();
        console.error("Failed to send message:", errorData);
        showNotification(errorData.error || "Failed to send message", "error");
        setLoading(false);
        return;
      }

      // Handle normal response (non-streaming)
      const data = await response.json();
      setMessages(prevMessages => [
        ...prevMessages,
        { text: data.response, sender: "ai", id: generateStableId('ai-msg') }
      ]);
      setLoading(false);
    } catch (error) {
      console.error("Error sending message:", error);
      showNotification("Error sending message: " + String(error), "error");
      setLoading(false);
    }
  };

  // Handle context operations
  const handleContextLoad = (contextId: string, chatHistory: string[]) => {
    setCurrentContextId(contextId);
    
    if (Array.isArray(chatHistory)) {
      try {
        // Transform chat history from simplified array format to MessageInterface format
        // Even indices (0, 2, 4, ...) are user messages, odd indices (1, 3, 5, ...) are AI messages
        const formattedHistory: MessageInterface[] = [];
        
        for (let i = 0; i < chatHistory.length; i++) {
          formattedHistory.push({
            text: chatHistory[i],
            sender: i % 2 === 0 ? "user" : "ai",
            id: `history-${i}`
          });
        }
        
        setMessages(formattedHistory);
        showNotification("Conversation loaded successfully", "success");
      } catch (error) {
        console.error("Error processing chat history:", error);
        showNotification("Error processing chat history", "error");
      }
    } else {
      showNotification("Invalid chat history format", "error");
    }
  };

  const handleContextReset = () => {
    setMessages([]);
    setCurrentContextId(null);
    showNotification("Started new conversation", "info");
  };

  // Notification handling
  const showNotification = (message: string, severity: "success" | "error" | "info" | "warning") => {
    setNotification({
      open: true,
      message,
      severity
    });
  };

  const handleCloseNotification = () => {
    setNotification({...notification, open: false});
  };

  return (
    <Box 
      sx={{ 
        display: "flex", 
        height: "100vh",
        background: theme.palette.mode === 'light' 
          ? 'linear-gradient(145deg, #f0f4f8 0%, #e8f0fb 100%)' 
          : 'linear-gradient(145deg, #111827 0%, #0f172a 100%)',
        position: 'relative',
        overflow: 'hidden'
      }}
    >
      {/* Background elements for visual interest */}
      <Box
        sx={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          overflow: 'hidden',
          zIndex: 0,
          opacity: 0.6,
        }}
      >
        {/* Top bubbles */}
        <Box
          sx={{
            position: 'absolute',
            top: '-15%',
            right: '-5%',
            width: '40%',
            height: '40%',
            borderRadius: '50%',
            background: theme.palette.mode === 'light' 
              ? 'radial-gradient(circle, rgba(173,216,230,0.2) 0%, rgba(173,216,230,0) 70%)' 
              : 'radial-gradient(circle, rgba(66,153,225,0.08) 0%, rgba(66,153,225,0) 70%)',
            filter: 'blur(50px)',
          }}
        />
        
        {/* Bottom left gradient */}
        <Box
          sx={{
            position: 'absolute',
            bottom: '-10%',
            left: '-5%',
            width: '35%',
            height: '40%',
            borderRadius: '50%',
            background: theme.palette.mode === 'light' 
              ? 'radial-gradient(circle, rgba(148,187,233,0.2) 0%, rgba(148,187,233,0) 60%)' 
              : 'radial-gradient(circle, rgba(79,94,120,0.1) 0%, rgba(79,94,120,0) 60%)',
            filter: 'blur(40px)',
          }}
        />
        
        {/* Middle right gradient */}
        <Box
          sx={{
            position: 'absolute',
            top: '30%',
            right: '-15%',
            width: '30%',
            height: '50%',
            borderRadius: '50%',
            transform: 'rotate(-15deg)',
            background: theme.palette.mode === 'light' 
              ? 'radial-gradient(ellipse, rgba(176,196,222,0.2) 0%, rgba(176,196,222,0) 70%)' 
              : 'radial-gradient(ellipse, rgba(90,100,120,0.1) 0%, rgba(90,100,120,0) 70%)',
            filter: 'blur(45px)',
          }}
        />
      </Box>

      {/* Sidebar with context management */}
      <Sidebar 
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onContextLoad={handleContextLoad}
        onContextReset={handleContextReset}
      />

      {/* Chat Content */}
      <Box
        display="flex"
        flexDirection="column"
        flexGrow={1}
        bgcolor="transparent"
        color="text.primary"
        sx={{
          // marginLeft: { xs: 0, sm: sidebarOpen ? "280px" : "0px" },
          transition: "margin 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
          width: { xs: '100%', sm: 'auto' },
          position: 'relative',
          zIndex: 1,
        }}
      >
        {/* Top Bar with Sidebar Toggle */}
        <Box sx={{ p: { xs: 1.5, sm: 2 } }}>
          <Paper
            elevation={0}
            sx={{
              display: "flex",
              alignItems: "center",
              p: { xs: 1.5, sm: 2 },
              borderRadius: 3,
              border: '1px solid',
              borderColor: 'divider',
              backdropFilter: 'blur(8px)',
              bgcolor: theme.palette.mode === 'light'
                ? 'rgba(255, 255, 255, 0.7)'
                : 'rgba(15, 23, 42, 0.6)',
              boxShadow: '0 4px 20px rgba(0,0,0,0.08)',
            }}
          >
            <IconButton 
              onClick={() => setSidebarOpen(!sidebarOpen)}
              sx={{ 
                mr: 1.5,
                transition: 'all 0.2s',
                bgcolor: sidebarOpen ? 'action.selected' : 'transparent',
                '&:hover': {
                  transform: 'scale(1.05)',
                  bgcolor: 'action.hover',
                }
              }}
            >
              {sidebarOpen ? <CloseIcon /> : <MenuIcon />}
            </IconButton>
            
            {!sidebarOpen && (
              <Fade in={!sidebarOpen}>
                <Box
                  component="img"
                  sx={{
                    height: { xs: 34, sm: 38 },
                    ml: { xs: 0, sm: 0.5 },
                    transition: 'transform 0.3s',
                    filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.1))',
                    '&:hover': {
                      transform: 'scale(1.05)'
                    }
                  }}
                  src="/CodeSage-Transparent.png"
                  alt="CodeSage Logo"
                />
              </Fade>
            )}
            
            <Box sx={{ flexGrow: 1 }} />
            
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
              <UploadModule />
            </Box>
          </Paper>
        </Box>
        
        {/* Chat Messages Container */}
        <Box 
          sx={{ 
            flex: 1, 
            display: 'flex', 
            flexDirection: 'column', 
            height: 'calc(100vh - 150px)', 
            overflow: 'hidden',
            position: 'relative',
          }}
        >
          <MessageContainer messages={messages} loading={loading} />
        </Box>

        {/* Chat Input */}
        <Box 
          sx={{ 
            position: 'sticky', 
            bottom: 0, 
            width: '100%', 
            zIndex: 10,
            mt: 'auto',
            pb: { xs: 1.5, sm: 2 },
            backdropFilter: 'blur(5px)'
          }}
        >
          <ChatInput onSend={handleSendMessage} models={models} />
        </Box>
      </Box>

      {/* Notifications */}
      <Snackbar
        open={notification.open}
        autoHideDuration={5000}
        onClose={handleCloseNotification}
        anchorOrigin={{ vertical: "top", horizontal: "center" }}
        sx={{ zIndex: 9999 }}
      >
        <Alert 
          onClose={handleCloseNotification} 
          severity={notification.severity}
          sx={{ 
            borderRadius: 2,
            boxShadow: '0 8px 16px rgba(0,0,0,0.1)',
            width: '100%',
            '& .MuiAlert-icon': {
              display: 'flex',
              alignItems: 'center'
            },
            backdropFilter: 'blur(8px)',
            border: '1px solid',
            borderColor: notification.severity === 'success' 
              ? 'success.light' 
              : notification.severity === 'error'
                ? 'error.light'
                : 'info.light',
          }}
          variant="filled"
        >
          {notification.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}