import { useState } from "react";
import { 
    Drawer, 
    List, 
    Box, 
    Typography,
    useTheme,
    useMediaQuery
} from "@mui/material";
import { styled } from "@mui/system";
import ContextManager from './ContextManager';

interface SidebarProps {
    open: boolean;
    onClose: () => void;
    onContextLoad?: (contextId: string, chatHistory: any) => void;
    onContextReset?: () => void;
    currentContextId: string | null; // Add current context ID prop
}

const StyledDrawer = styled(Drawer)(({ theme }) => ({
    flexShrink: 0,
    "& .MuiDrawer-paper": {
        width: '280px',
        boxSizing: "border-box",
        display: "flex",
        flexDirection: "column",
        backgroundImage: `linear-gradient(to bottom, ${theme.palette.background.paper}, ${theme.palette.background.default})`,
        borderRight: `1px solid ${theme.palette.divider}`,
        boxShadow: '4px 0 15px rgba(0, 0, 0, 0.05)',
        overflowX: 'hidden',
        transition: 'width 0.3s ease',
    },
    "@media (max-width: 600px)": {
        "& .MuiDrawer-paper": {
            width: '85vw',
        },
    }
}));

const ScrollableList = styled(List)({
    flexGrow: 1,
    overflowY: "auto",
    overflowX: "hidden",
    scrollbarWidth: "thin",
    "&::-webkit-scrollbar": {
        width: "6px",
    },
    "&::-webkit-scrollbar-track": {
        background: "transparent"
    },
    "&::-webkit-scrollbar-thumb": {
        backgroundColor: 'rgba(0, 0, 0, 0.1)',
        borderRadius: "20px",
        border: "2px solid transparent",
        backgroundClip: "content-box"
    },
    "&::-webkit-scrollbar-thumb:hover": {
        backgroundColor: 'rgba(0, 0, 0, 0.2)',
    }
});

export default function Sidebar({ open, onClose, onContextLoad, onContextReset, currentContextId }: SidebarProps) {
    const theme = useTheme();
    const isMobile = useMediaQuery(theme.breakpoints.down('sm'));

    return (
        <StyledDrawer
            anchor="left"
            open={open}
            onClose={onClose}
        >
            {/* Logo and Header */}
            <Box 
                sx={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    py: 3,
                    px: 2,
                }}
            >
                <Box 
                    component="img" 
                    sx={{ 
                        maxWidth: "180px", 
                        mb: 2,
                        transition: 'transform 0.3s',
                        '&:hover': {
                            transform: 'scale(1.05)'
                        }
                    }} 
                    src="/CodeSage-Transparent.png" 
                    alt="CodeSage Logo" 
                />
            </Box>
            
            {/* Conversations list */}
            <Box sx={{ px: 2, py: 1 }}>
                <ContextManager 
                    onContextLoad={onContextLoad || (() => {})} 
                    onContextReset={onContextReset || (() => {})}
                    currentContextId={currentContextId}
                />
            </Box>
            
            <ScrollableList sx={{ py: 0 }}>
                {/* Future sidebar items can go here */}
            </ScrollableList>
        </StyledDrawer>
    );
}
