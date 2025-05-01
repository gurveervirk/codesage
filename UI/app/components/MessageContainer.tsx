import { Box, CircularProgress, Typography, useTheme, Paper, Fade } from "@mui/material";
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
    const theme = useTheme();
    
    // Smooth scroll to the bottom whenever messages change or loading status changes
    useEffect(() => {
        if (chatContainerRef.current) {
            const container = chatContainerRef.current;
            const isScrolledToBottom = container.scrollHeight - container.clientHeight <= container.scrollTop + 150;
            
            if (isScrolledToBottom || loading) {
                // Use smooth scrolling animation
                setTimeout(() => {
                    container.scrollTo({
                        top: container.scrollHeight,
                        behavior: "smooth"
                    });
                }, 100);
            }
        }
    }, [messages, loading]);
    
    return (
        <Box 
            ref={chatContainerRef} 
            flexGrow={1} 
            overflow="auto" 
            p={{ xs: 2, sm: 3, md: 4 }} 
            mx="auto"
            maxWidth="1000px"
            width="100%"
            sx={{
                display: "flex",
                flexDirection: "column",
                overscrollBehavior: "contain",
                scrollbarWidth: "thin",
                scrollbarColor: `${theme.palette.primary.light} transparent`,
                "&::-webkit-scrollbar": {
                    width: "6px",
                },
                "&::-webkit-scrollbar-track": {
                    background: "transparent"
                },
                "&::-webkit-scrollbar-thumb": {
                    backgroundColor: theme.palette.mode === 'light' 
                        ? 'rgba(0, 0, 0, 0.2)' 
                        : 'rgba(255, 255, 255, 0.2)',
                    borderRadius: "20px",
                    border: "2px solid transparent",
                    backgroundClip: "content-box"
                },
                "&::-webkit-scrollbar-thumb:hover": {
                    backgroundColor: theme.palette.mode === 'light' 
                        ? 'rgba(0, 0, 0, 0.35)' 
                        : 'rgba(255, 255, 255, 0.35)',
                }
            }}
        >
            {/* Welcome message if no messages */}
            {messages.length === 0 && !loading && (
                <Fade in={true} timeout={800}>
                    <Box 
                        display="flex" 
                        flexDirection="column" 
                        alignItems="center" 
                        justifyContent="center" 
                        height="100%"
                        textAlign="center"
                        sx={{ 
                            py: 6,
                            px: 3,
                            borderRadius: 4,
                            background: theme.palette.mode === 'light' 
                                ? 'linear-gradient(145deg, rgba(255,255,255,0.7) 0%, rgba(240,245,255,0.7) 100%)' 
                                : 'linear-gradient(145deg, rgba(25,35,60,0.4) 0%, rgba(15,25,45,0.4) 100%)',
                            backdropFilter: 'blur(10px)',
                            border: '1px solid',
                            borderColor: theme.palette.mode === 'light' 
                                ? 'rgba(230,235,250,0.8)' 
                                : 'rgba(50,65,90,0.5)',
                            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.1)'
                        }}
                    >
                        <Box
                            component="img"
                            src="/CodeSage-Transparent.png"
                            alt="CodeSage Logo"
                            sx={{
                                height: { xs: 60, sm: 80 },
                                mb: 3,
                                opacity: 0.9,
                                filter: 'drop-shadow(0 4px 6px rgba(0,0,0,0.1))'
                            }}
                        />
                        <Typography variant="h4" color="primary.dark" fontWeight={700} gutterBottom sx={{ mb: 2 }}>
                            Welcome to CodeSage
                        </Typography>
                        <Typography variant="body1" color="text.secondary" sx={{ 
                            maxWidth: 600, 
                            mx: 'auto',
                            mb: 3,
                            fontSize: { xs: '1rem', sm: '1.1rem' },
                            lineHeight: 1.6
                        }}>
                            Your intelligent AI assistant that helps analyze and generate code.
                            <br />
                            How can I help you today?
                        </Typography>
                    </Box>
                </Fade>
            )}

            {/* Message list */}
            {messages.map((msg, index) => (
                <Message key={msg.id || index} msg={msg} index={index} />
            ))}

            {/* Loading indicator */}
            {loading && (
                <Box 
                    alignSelf="flex-start" 
                    mt={2} 
                    mb={1}
                    ml={1}
                    display="flex" 
                    alignItems="center"
                >
                    <Paper 
                        elevation={2} 
                        sx={{ 
                            p: 1.5, 
                            borderRadius: '18px 18px 18px 4px',
                            display: 'inline-flex',
                            alignItems: 'center',
                            bgcolor: theme.palette.background.paper,
                            boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
                            border: '1px solid',
                            borderColor: 'divider',
                        }}
                    >
                        <Box 
                            sx={{ 
                                display: 'flex', 
                                alignItems: 'center',
                                position: 'relative',
                                mr: 1.5,
                            }}
                        >
                            <CircularProgress 
                                size={24} 
                                thickness={5} 
                                sx={{ 
                                    color: theme.palette.primary.main,
                                }} 
                            />
                            <Box 
                                sx={{
                                    position: 'absolute',
                                    top: 0,
                                    left: 0,
                                    bottom: 0,
                                    right: 0,
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                }}
                            >
                                <Box 
                                    component="span"
                                    sx={{
                                        width: 6,
                                        height: 6,
                                        bgcolor: theme.palette.secondary.main,
                                        borderRadius: '50%',
                                    }}
                                />
                            </Box>
                        </Box>
                        <Typography 
                            variant="body2" 
                            sx={{
                                background: 'linear-gradient(45deg, #1976d2, #7e57c2)',
                                backgroundClip: 'text',
                                WebkitBackgroundClip: 'text',
                                WebkitTextFillColor: 'transparent',
                                fontWeight: 500,
                            }}
                        >
                            Thinking...
                        </Typography>
                    </Paper>
                </Box>
            )}

            {/* Spacer at the bottom to ensure messages don't hide behind the input box on mobile */}
            <Box sx={{ height: { xs: '100px', sm: '40px' } }} />
        </Box>
    );
}
