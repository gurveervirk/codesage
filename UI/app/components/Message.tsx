import React, { memo, useState, useEffect } from "react";
import { Box, Avatar, Typography, Fade, useTheme, useMediaQuery } from '@mui/material';
import MarkdownRenderer from './MarkdownRenderer';
import PersonIcon from '@mui/icons-material/Person';
import SmartToyIcon from '@mui/icons-material/SmartToy';

interface MessageProps {
  msg: {
    sender: "user" | "ai";
    text: string;
    id: string;
  };
  index: number;
}

const Message: React.FC<MessageProps> = memo(({ msg, index }) => {
  const isUser = msg.sender === "user";
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('sm'));
  const [timestamp, setTimestamp] = useState<string | null>(null);
  
  // Only set the timestamp on the client after component mounts
  useEffect(() => {
    setTimestamp(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
  }, []);
  
  return (
    <Fade in={true} timeout={300} style={{ transitionDelay: `${index * 50}ms` }}>
      <Box
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
            bgcolor: isUser 
              ? 'primary.main' 
              : theme.palette.mode === 'light' 
                ? 'secondary.main' 
                : 'secondary.dark',
            width: { xs: 32, sm: 38 },
            height: { xs: 32, sm: 38 },
            mr: isUser ? 0 : 1.5,
            ml: isUser ? 1.5 : 0,
            boxShadow: '0 3px 10px rgba(0,0,0,0.15)',
            transition: 'all 0.2s ease',
            '&:hover': {
              transform: 'scale(1.05)',
              boxShadow: '0 5px 15px rgba(0,0,0,0.2)',
            }
          }}
        >
          {isUser ? <PersonIcon fontSize={isMobile ? "small" : "medium"} /> : <SmartToyIcon fontSize={isMobile ? "small" : "medium"} />}
        </Avatar>

        {/* Message bubble */}
        <Box
          sx={{
            position: 'relative',
            p: { xs: 1.5, sm: 2 },
            borderRadius: isUser 
              ? { xs: "18px 4px 18px 18px", sm: "20px 4px 20px 20px" } 
              : { xs: "4px 18px 18px 18px", sm: "4px 20px 20px 20px" },
            maxWidth: { xs: "80%", sm: "70%", md: "65%" },
            bgcolor: isUser 
              ? theme.palette.mode === 'light'
                ? 'primary.main'
                : 'primary.dark'
              : theme.palette.mode === 'light' 
                ? 'background.default' 
                : 'background.paper',
            color: isUser ? 'primary.contrastText' : 'text.primary',
            wordBreak: "break-word",
            boxShadow: isUser 
              ? '0 3px 12px rgba(25, 118, 210, 0.3)'
              : '0 3px 12px rgba(0, 0, 0, 0.1)',
            border: isUser 
              ? 'none'
              : `1px solid ${theme.palette.divider}`,
            fontFamily: theme.typography.fontFamily,
            fontSize: { xs: '14px', sm: '15px' },
            lineHeight: 1.6,
            transition: 'all 0.2s ease',
            '&:hover': {
              boxShadow: isUser 
                ? '0 5px 15px rgba(25, 118, 210, 0.35)'
                : '0 5px 15px rgba(0, 0, 0, 0.15)',
              transform: 'translateY(-2px)',
            },
            '&::before': {
              content: '""',
              position: 'absolute',
              top: 12,
              [isUser ? 'right' : 'left']: -8,
              width: 16,
              height: 16,
              backgroundColor: isUser 
                ? theme.palette.mode === 'light' ? 'primary.main' : 'primary.dark' 
                : theme.palette.mode === 'light' ? 'background.default' : 'background.paper',
              border: isUser 
                ? 'none'
                : `1px solid ${theme.palette.divider}`,
              borderRight: isUser ? 'none' : '0',
              borderBottom: isUser ? 'none' : '0',
              borderTop: isUser ? '0' : '0',
              borderLeft: isUser ? '0' : 'none',
              transform: isUser 
                ? 'rotate(45deg)'
                : 'rotate(45deg)',
              zIndex: 0,
            }
          }}
        >
          <Box sx={{ position: 'relative', zIndex: 1 }}>
            <MarkdownRenderer content={msg.text} isUserMessage={isUser} />
          </Box>
          
          {/* Timestamp - Only rendered client-side after component mount */}
          {timestamp && (
            <Typography
              variant="caption"
              sx={{
                position: 'absolute',
                bottom: 6,
                right: isUser ? 'auto' : 12,
                left: isUser ? 12 : 'auto',
                color: isUser ? 'rgba(255,255,255,0.7)' : 'text.secondary',
                fontSize: '0.65rem',
                opacity: 0.8,
                mt: 1,
                display: { xs: 'none', sm: 'block' },
                fontStyle: 'italic'
              }}
            >
              {timestamp}
            </Typography>
          )}
        </Box>
      </Box>
    </Fade>
  );
});

export default Message;