// app/routes/chat.tsx
import { useState } from "react";
import { Box, IconButton } from "@mui/material";
import MenuIcon from "@mui/icons-material/Menu";
import CloseIcon from "@mui/icons-material/Close";
import Sidebar from "~/components/Sidebar";
import UploadModule from "~/components/UploadModule";
import MessageContainer from "~/components/MessageContainer";
import ChatInput from "~/components/ChatInput";
import { useLoaderData } from "@remix-run/react";
import {loader as available_models_loader} from "~/loaders/available_models";
export {available_models_loader as loader} 
import { Model } from "~/components/ChatInput";
interface Message {
  text: string;
  sender: "user" | "ai";
}

export default function Chat() {
  const models = useLoaderData<{ [key: string]: Model[] }>();
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const sendMessage = (message: string) => {
    setMessages([...messages, { text: message, sender: "user" }]);
    setLoading(true);

    setTimeout(() => {
      setMessages((prev) => [...prev, { text: "This is a sample AI response.", sender: "ai" }]);
      setLoading(false);
    }, 1500);
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
        sx={{ marginLeft: sidebarOpen ? "15vw" : "0px", transition: "margin 0.3s ease-in-out" }}
      >
        {/* Top Bar with Sidebar Toggle */}
        <Box display="flex" alignItems="center" mb={2}>
          <IconButton onClick={() => setSidebarOpen(!sidebarOpen)}>
            {sidebarOpen ? <CloseIcon /> : <MenuIcon />}
          </IconButton>
          {!sidebarOpen && (
            <Box component="img" sx={{ marginLeft: "4px", inlineSize: "80px" }} src="CodeSage-Transparent.png" />
          )}
          <Box ml="auto">
            <UploadModule />
          </Box>
        </Box>
        {/* Upload Module Button */}
        {/* Chat Messages */}
        <MessageContainer messages={messages} loading={loading} />

        {/* Chat Input */}
        <ChatInput onSend={sendMessage} models={models}/>
      </Box>
    </Box>
  );
}
