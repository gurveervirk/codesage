import { Box, CircularProgress, Typography } from "@mui/material";
import { useRef, useEffect } from "react";
import Message from "./Message";
export interface MessageInterface {
    text: string;
    sender: "user" | "ai";
    id: string;
}

export interface MessageContainerProps {
    messages: MessageInterface[];
    loading: boolean;

}

export function MessageContainer({ messages, loading }: MessageContainerProps) {
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
                <Message key={index} msg={msg} index={index} />
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
