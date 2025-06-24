import { useState } from 'react';
import { Dialog, Tabs, Tab, Box, TextField, Button, Stack } from '@mui/material';

interface SettingsModalProps {
    open: boolean;
    handleClose: () => void;
}

const SettingsModal: React.FC<SettingsModalProps> = ({ open, handleClose }) => {
    const [activeTab, setActiveTab] = useState(0);

    const handleTabChange = (event: React.ChangeEvent<{}>, newValue: number) => {
        setActiveTab(newValue);
    };

    return (
        <Dialog maxWidth={"xl"} open={open} onClose={handleClose}>
            <Box sx={{ width: '100%', height: '100%', p: 2 }}>
                <Tabs value={activeTab} onChange={handleTabChange} centered>
                    <Tab label="General" />
                    <Tab label="Account" />
                    <Tab label="LLM Settings" />
                    <Tab label="Notifications" />
                </Tabs>
                {activeTab === 0 && (
                    <Box p={3}>
                        <form>
                            <Stack spacing={2} alignItems="center">
                                <Box width="100%">
                                    <label>General Setting 1</label>
                                    <TextField fullWidth margin="normal" />
                                </Box>
                                <Box width="100%">
                                    <label>General Setting 2</label>
                                    <TextField fullWidth margin="normal" />
                                </Box>
                                <Box width="100%">
                                    <Button variant="contained" color="primary" type="submit">Save</Button>
                                </Box>
                            </Stack>
                        </form>
                    </Box>
                )}
                {activeTab === 1 && (
                    <Box p={3}>
                        <form>
                            <Stack spacing={2} alignItems="center">
                                <Box width="100%">
                                    <label>Account Setting 1</label>
                                    <TextField fullWidth margin="normal" />
                                </Box>
                                <Box width="100%">
                                    <label>Account Setting 2</label>
                                    <TextField fullWidth margin="normal" />
                                </Box>
                                <Box width="100%">
                                    <Button variant="contained" color="primary" type="submit">Save</Button>
                                </Box>
                            </Stack>
                        </form>
                    </Box>
                )}
                {activeTab === 2 && (
                    <Box p={3}>
                        <form>
                            <Stack spacing={2} alignItems="center">
                                <Box width="100%">
                                    <label>Model Name</label>
                                    <TextField fullWidth margin="normal" />
                                </Box>
                                <Box width="100%">
                                    <Button variant="contained" color="primary" type="submit">Save</Button>
                                </Box>
                            </Stack>
                        </form>
                    </Box>
                )}
                {activeTab === 3 && (
                    <Box p={3}>
                        <form>
                            <Stack spacing={2} alignItems="center">
                                <Box width="100%">
                                    <label>Notification Setting 1</label>
                                    <TextField fullWidth margin="normal" />
                                </Box>
                                <Box width="100%">
                                    <label>Notification Setting 2</label>
                                    <TextField fullWidth margin="normal" />
                                </Box>
                                <Box width="100%">
                                    <Button variant="contained" color="primary" type="submit">Save</Button>
                                </Box>
                            </Stack>
                        </form>
                    </Box>
                )}
            </Box>
        </Dialog>
    );
};

export default SettingsModal;
