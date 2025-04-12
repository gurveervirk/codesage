import React, { memo } from "react";
import { Box, Avatar, Typography, Fade } from '@mui/material';
import MarkdownRenderer from './MarkdownRenderer';
import PersonIcon from '@mui/icons-material/Person';
import SmartToyIcon from '@mui/icons-material/SmartToy';

interface MessageProps {
  msg: {
    sender: "user" | "ai";
    text: string;
  };
  index: number;
}

const Message: React.FC<MessageProps> = memo(({ msg, index }) => {
  const isUser = msg.sender === "user";
  
  return (
    <Fade in={true} timeout={300}>
      <Box
        key={index}
        display="flex"
        flexDirection={isUser ? "row-reverse" : "row"}
        alignItems="flex-start"
        mb={3}
        width="100%"
        sx={{ position: 'relative' }}
      >
        {/* Avatar */}
        <Avatar
          sx={{
            bgcolor: isUser ? 'primary.main' : 'secondary.main',
            width: 38,
            height: 38,
            mr: isUser ? 0 : 1.5,
            ml: isUser ? 1.5 : 0,
            boxShadow: 2,
          }}
        >
          {isUser ? <PersonIcon /> : <SmartToyIcon />}
        </Avatar>

        {/* Message bubble */}
        <Box
          sx={{
            position: 'relative',
            p: 2,
            borderRadius: isUser ? "18px 4px 18px 18px" : "4px 18px 18px 18px",
            maxWidth: "80%",
            bgcolor: isUser ? 'primary.main' : 'background.paper',
            color: isUser ? 'primary.contrastText' : 'text.primary',
            wordBreak: "break-word",
            whiteSpace: "pre-wrap",
            boxShadow: '0 2px 10px rgba(0,0,0,0.08)',
            fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
            fontSize: '15px',
            lineHeight: 1.6,
            letterSpacing: '0.00938em',
            '&::before': {
              content: '""',
              position: 'absolute',
              top: 0,
              [isUser ? 'right' : 'left']: -10,
              width: 20,
              height: 20,
              backgroundColor: isUser ? 'primary.main' : 'background.paper',
              clipPath: isUser 
                ? 'polygon(100% 0, 0 0, 100% 100%)' 
                : 'polygon(0 0, 100% 0, 0 100%)',
            }
          }}
        >
          <MarkdownRenderer content={msg.text} />
          
          {/* Timestamp (optional) */}
          <Typography
            variant="caption"
            sx={{
              position: 'absolute',
              bottom: 4,
              right: isUser ? 'auto' : 10,
              left: isUser ? 10 : 'auto',
              color: isUser ? 'rgba(255,255,255,0.7)' : 'text.secondary',
              fontSize: '0.65rem',
              opacity: 0.8,
              mt: 1
            }}
          >
            {new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </Typography>
        </Box>
      </Box>
    </Fade>
  );
});

export default Message;