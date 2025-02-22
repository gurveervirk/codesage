import { Box, CircularProgress, Typography } from "@mui/material";
import { useRef, useEffect } from "react";
interface Message {
    text: string;
    sender: "user" | "ai";
}

interface MessageContainerProps {
    messages: Message[];
    loading: boolean;

}

export default function MessageContainer({ messages, loading }: MessageContainerProps) {
    const chatContainerRef = useRef<HTMLDivElement>(null);

    // Scroll to the bottom whenever messages change or loading is true
    useEffect(() => {
        if (chatContainerRef.current) {
            chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
        }
    }, [messages, loading]);
    return (
        <Box ref={chatContainerRef} flexGrow={1} overflow="auto" p={2} sx={{
            display: "flex",
            flexDirection: "column",
        }}>
            {messages.map((msg, index) => (
                <Box
                    key={index}
                    display="flex"
                    justifyContent={msg.sender === "user" ? "flex-end" : "flex-start"}
                    mb={1}
                >
                    <Typography
                        sx={{
                            p: 1,
                            borderRadius: "16px",
                            maxWidth: "fit-content",
                            bgcolor: msg.sender === "user" ? "primary.main" : "grey.300",
                            color: msg.sender === "user" ? "primary.contrastText" : "text.primary",
                            wordBreak: "break-word",
                        }}
                    >
                        {msg.text}
                    </Typography>
                </Box>
            ))}

            {/* Loading Indicator */}
            {loading && (
                <Box display="flex" justifyContent="left" mt={2}>
                    <CircularProgress size={24} />
                </Box>
            )}
        </Box>
    );
}
