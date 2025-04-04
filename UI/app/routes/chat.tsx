// app/routes/chat.tsx
import { useState, useRef, useEffect } from "react";
import { Box, IconButton } from "@mui/material";
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

export default function Chat() {
  const models = useLoaderData<{ [key: string]: Model[] }>();
  const [messages, setMessages] = useState<MessageInterface[]>([]);
  const [loading, setLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
      console.log(models);
    }, [models]);

  const handleSendMessage = async (message: string) => {
    // 1. Add user message to the state immediately
    const newMessage: MessageInterface = { text: message, sender: "user", id: Date.now().toString() };
    setMessages((prevMessages) => [...prevMessages, newMessage]);
    setLoading(true);

    // 2. Close existing EventSource if it exists
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    // 3. POST to /api/chat and then establish EventSource
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        body: JSON.stringify({ prompt: message }),
        headers: {
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        console.error("Failed to store prompt:", response);
        setLoading(false);
        return;
      }

      const es = new EventSource(`/api/chat`);

      es.onmessage = (event) => {
        const data = JSON.parse(event.data); // Parse the JSON string
          const wrappedResponse = data.wrapped_response;  // Extract the encapsulated response
          console.log("EventSource message:", wrappedResponse);
        setMessages((prevMessages) => {
          const lastMessage = prevMessages[prevMessages.length - 1];
          if (lastMessage && lastMessage.sender === "ai") {
            // Update the last AI message with the new chunk
            const updatedMessage = { ...lastMessage, text:  wrappedResponse };
            const newMessages = [...prevMessages];
            newMessages[prevMessages.length - 1] = updatedMessage;
            return newMessages;
          } else {
            // Add a new AI message
            return [...prevMessages, { text: event.data, sender: "ai", id: Date.now().toString() }];
          }
        });
        setLoading(false);
      };

      es.onerror = (event) => {
        console.error("EventSource error:", event);
        es.close();
        setLoading(false);
      };

      es.onopen = () => {
        setLoading(false);
      };

      // 4. Store the EventSource reference
      eventSourceRef.current = es;
    } catch (error) {
      console.error("Error sending message or setting up stream:", error);
      setLoading(false);
    }
  };

  return (
    <Box display="flex" padding={"10px"} height="100vh">
      {/* Sidebar */}
      <Sidebar open={sidebarOpen} />

      {/* Chat Content */}
      <Box
        display="flex"
        flexDirection="column"
        flexGrow={1}
        p={2}
        bgcolor="background.default"
        color="text.primary"
        sx={{
          marginLeft: sidebarOpen ? "15vw" : "0px",
          transition: "margin 0.3s ease-in-out",
        }}
      >
        {/* Top Bar with Sidebar Toggle */}
        <Box display="flex" alignItems="center" mb={2}>
          <IconButton onClick={() => setSidebarOpen(!sidebarOpen)}>
            {sidebarOpen ? <CloseIcon /> : <MenuIcon />}
          </IconButton>
          {!sidebarOpen && (
            <Box
              component="img"
              sx={{ marginLeft: "4px", inlineSize: "80px" }}
              src="CodeSage-Transparent.png"
            />
          )}
          <Box ml="auto">
            <UploadModule />
          </Box>
        </Box>
        {/* Upload Module Button */}
        {/* Chat Messages */}
        <MessageContainer messages={messages} loading={loading} />

        {/* Chat Input */}
        <ChatInput onSend={handleSendMessage} models={models} />
      </Box>
    </Box>
  );
}