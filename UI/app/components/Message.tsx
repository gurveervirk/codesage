import React, { memo } from "react";
import { Box, Typography } from '@mui/material';
interface MessageProps {
    msg: {
        sender: "user"|"ai";
        text: string;
    };
    index: number;
}

const Message: React.FC<MessageProps> = memo(({ msg, index }) => {
    return (
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
                    whiteSpace: "pre-wrap",
                }}
            >
                {msg.text}
            </Typography>
        </Box>
    );
});

export default Message;