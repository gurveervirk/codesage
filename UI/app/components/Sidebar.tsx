import { useState } from "react";
import { 
    Drawer, 
    List, 
    Box, 
    ListItem, 
    ListItemText, 
    ListItemIcon, 
    Divider, 
    Typography,
    Collapse,
    useTheme,
    useMediaQuery,
    IconButton,
    Avatar,
    Tooltip
} from "@mui/material";
import { styled } from "@mui/system";
import SettingsIcon from '@mui/icons-material/Settings';
import ChevronRightIcon from '@mui/icons-material/ChevronRight';
import HistoryIcon from '@mui/icons-material/History';
import DashboardIcon from '@mui/icons-material/Dashboard';
import ExpandLess from '@mui/icons-material/ExpandLess';
import ExpandMore from '@mui/icons-material/ExpandMore';
import ContextManager from './ContextManager';
import SettingsModal from './Settings';

interface SidebarProps {
    open: boolean;
    onClose: () => void;
    onContextLoad?: (contextId: string, chatHistory: any) => void;
    onContextReset?: () => void;
}

const StyledListItem = styled(ListItem)<{active?: number}>(({ theme, active }) => ({
    borderRadius: '8px',
    margin: '4px 8px',
    padding: '10px 16px',
    transition: 'all 0.2s ease',
    cursor: 'pointer',
    "&:hover": {
        backgroundColor: theme.palette.action.hover,
        transform: 'translateX(4px)',
    },
    ...(active && {
        backgroundColor: theme.palette.action.selected,
        "&::before": {
            content: '""',
            position: 'absolute',
            left: 0,
            top: '50%',
            transform: 'translateY(-50%)',
            width: '4px',
            height: '60%',
            backgroundColor: theme.palette.primary.main,
            borderRadius: '0 4px 4px 0',
        }
    })
}));

const StyledDrawer = styled(Drawer)(({ theme }) => ({
    // width: '280px',
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

const BottomList = styled(List)(({ theme }) => ({
    borderTop: `1px solid ${theme.palette.divider}`,
    backgroundColor: theme.palette.background.paper,
    backdropFilter: 'blur(10px)',
}));

export default function Sidebar({ open, onClose, onContextLoad, onContextReset }: SidebarProps) {
    const [isSettingsOpen, setIsSettingsOpen] = useState(false);
    const [conversationsOpen, setConversationsOpen] = useState(true);
    const theme = useTheme();
    const isMobile = useMediaQuery(theme.breakpoints.down('sm'));

    const handleSettingsClick = () => {
        setIsSettingsOpen(true);
    };

    const handleClose = () => {
        setIsSettingsOpen(false);
    };

    const toggleConversations = () => {
        setConversationsOpen(!conversationsOpen);
    };

    return (
        <>
            <StyledDrawer
                anchor="left"
                open={open}
                onClose={onClose}
                // variant="persistent"
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
                        src="CodeSage-Transparent.png" 
                        alt="CodeSage Logo" 
                    />
                    {/* User profile section - can be expanded later */}
                    <Box
                        sx={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 1.5,
                            p: 1,
                            width: '100%',
                            borderRadius: 2,
                            border: '1px solid',
                            borderColor: 'divider',
                            bgcolor: theme.palette.background.default,
                            mt: 1,
                        }}
                    >
                        <Avatar
                            sx={{
                                bgcolor: 'primary.main',
                                width: 36,
                                height: 36,
                            }}
                        >
                            U
                        </Avatar>
                        <Box>
                            <Typography
                                variant="subtitle2"
                                fontWeight={600}
                                sx={{
                                    lineHeight: 1.2,
                                    color: 'text.primary',
                                    fontSize: '0.875rem',
                                }}
                            >
                                User Session
                            </Typography>
                            <Typography
                                variant="caption"
                                sx={{
                                    color: 'text.secondary',
                                    fontSize: '0.75rem',
                                }}
                            >
                                Signed in as Guest
                            </Typography>
                        </Box>
                        <Box flexGrow={1} />
                        <Tooltip title="View profile settings">
                            <IconButton
                                size="small"
                                sx={{
                                    bgcolor: 'action.hover',
                                    '&:hover': {
                                        bgcolor: 'action.selected',
                                    },
                                }}
                            >
                                <ChevronRightIcon fontSize="small" />
                            </IconButton>
                        </Tooltip>
                    </Box>
                </Box>
                
                <Divider sx={{ mx: 2 }} />
                
                {/* Main navigation */}
                <List sx={{ py: 1 }}>
                    <StyledListItem active={1}>
                        <ListItemIcon>
                            <DashboardIcon color="primary" />
                        </ListItemIcon>
                        <ListItemText 
                            primary={
                                <Typography variant="body2" fontWeight={500}>
                                    Dashboard
                                </Typography>
                            } 
                        />
                    </StyledListItem>
                    
                    <StyledListItem onClick={toggleConversations}>
                        <ListItemIcon>
                            <HistoryIcon />
                        </ListItemIcon>
                        <ListItemText 
                            primary={
                                <Typography variant="body2" fontWeight={500}>
                                    Conversations
                                </Typography>
                            } 
                        />
                        {conversationsOpen ? <ExpandLess fontSize="small" /> : <ExpandMore fontSize="small" />}
                    </StyledListItem>
                    
                    <Collapse in={conversationsOpen} timeout="auto" unmountOnExit>
                        <Box sx={{ px: 2, py: 1 }}>
                            <ContextManager 
                                onContextLoad={onContextLoad || (() => {})} 
                                onContextReset={onContextReset || (() => {})} 
                            />
                        </Box>
                    </Collapse>
                </List>
                
                <ScrollableList sx={{ py: 0 }}>
                    {/* Future sidebar items can go here */}
                </ScrollableList>
                
                <BottomList>
                    <StyledListItem onClick={handleSettingsClick}>
                        <ListItemIcon>
                            <SettingsIcon />
                        </ListItemIcon>
                        <ListItemText 
                            primary={
                                <Typography variant="body2" fontWeight={500}>
                                    Settings
                                </Typography>
                            }
                        />
                    </StyledListItem>
                </BottomList>
            </StyledDrawer>
            
            <SettingsModal
                open={isSettingsOpen}
                handleClose={handleClose}
            />
        </>
    );
}
