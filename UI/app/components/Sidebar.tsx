import { useState } from "react";
import { Drawer, List, Box, ListItem, ListItemText, ListItemIcon, Modal } from "@mui/material";
import { styled } from "@mui/system";
import SettingsIcon from '@mui/icons-material/Settings';
import SettingsModal from './Settings'  // Import the Setting component

interface SidebarProps {
    open: boolean;
}

const StyledListItem = styled(ListItem)(({ theme }) => ({
    "&:hover": {
        backgroundColor: theme.palette.action.hover,
    },
    "&.Mui-selected": {
        backgroundColor: theme.palette.action.selected,
    },
    padding: theme.spacing(2),
}));

const StyledDrawer = styled(Drawer)(({ theme }) => ({
    "& .MuiDrawer-paper": {
        width: "15vw",
        boxSizing: "border-box",
        display: "flex",
        flexDirection: "column",
    },
}));

const ScrollableList = styled(List)({
    flexGrow: 1,
    overflowY: "auto",
});

const BottomList = styled(List)({
    borderTop: "1px solid rgba(0, 0, 0, 0.12)",
});

export default function Sidebar({ open }: SidebarProps) {
    // const [isSettingsOpen, setIsSettingsOpen] = useState(false);

    // const handleSettingsClick = () => {
    //     setIsSettingsOpen(true);
    // };

    // const handleClose = () => {
    //     setIsSettingsOpen(false);
    // };

    return (
        <>
            <StyledDrawer
                anchor="left"
                open={open}
                variant="persistent"
            >
                <Box component="img" sx={{ margin: "8px", inlineSize: "90%" }} src="CodeSage-Transparent.png" alt="Sidebar Closed" />
                <ScrollableList>
                    <StyledListItem>
                        <ListItemText primary="Dummy Item 1" />
                    </StyledListItem>
                    <StyledListItem>
                        <ListItemText primary="Dummy Item 2" />
                    </StyledListItem>
                    <StyledListItem>
                        <ListItemText primary="Dummy Item 3" />
                    </StyledListItem>
                </ScrollableList>
                {/* <BottomList>
                    <StyledListItem onClick={handleSettingsClick}>
                        <ListItemIcon>
                            <SettingsIcon />
                        </ListItemIcon>
                        <ListItemText primary="Settings" />
                    </StyledListItem>
                </BottomList> */}
            </StyledDrawer>
            {/* <SettingsModal
                open={isSettingsOpen}
                handleClose={handleClose}
            /> */}
        </>
    );
}
