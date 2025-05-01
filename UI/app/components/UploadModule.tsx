import React, { useState } from 'react';
import { Button, Modal, Box, FormControl, TextField, CircularProgress, Typography, IconButton, Tooltip, Paper, Fade, Backdrop } from '@mui/material';
import UploadIcon from '@mui/icons-material/Upload';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import { Form, useFetcher } from '@remix-run/react';

interface ApiResponse {
    message: string;
}

const UploadModule: React.FC = () => {
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const [successMessage, setSuccessMessage] = useState<string | null>(null);
    const [errorMessage, setErrorMessage] = useState<string | null>(null);
    const fetcher = useFetcher();
    const handleOpen = () => setOpen(true);
    const handleClose = () => {
        setOpen(false);
        setSuccessMessage(null);
        setErrorMessage(null);
    };

    const handleSubmit = async (event: React.FormEvent) => {
        event.preventDefault();
        setSuccessMessage(null);
        setErrorMessage(null);
        setLoading(true);

        try {
            const inputBox = event.currentTarget as HTMLFormElement;
            const formData = new FormData(inputBox);
            const moduleName = formData.get('moduleName') as string;

            fetcher.submit(
                { module_name: moduleName },
                { 
                    method: 'post', 
                    action: '/api/upload_module',
                    encType: 'application/json'
                }
            );

            if (fetcher.data) {
                console.log(fetcher.data);
                if ((fetcher.data as any).success) {
                    const data = fetcher.data as ApiResponse;
                    setSuccessMessage(data.message || "Module processed successfully!");
                    setErrorMessage(null);
                    inputBox.reset();
                }
                else {
                    const errorData: ApiResponse = fetcher.data as ApiResponse;
                    const errorMessage = errorData.message || "An unknown error occurred.";
                    throw new Error(errorMessage);
                }
            }
        } catch (error: any) {
            console.error("Error processing module:", error);
            setErrorMessage(error.message);
            setSuccessMessage(null);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div>
            <Button
                variant="outlined"
                startIcon={<UploadIcon />}
                onClick={handleOpen}
                sx={{ backgroundColor: 'whitesmoke', color: 'black', ":hover": { backgroundColor: 'ghostwhite' } }}
            >
                Ingest Module
            </Button>
            <Modal 
                open={open} 
                onClose={handleClose}
                closeAfterTransition
                slots={{ backdrop: Backdrop }}
                slotProps={{
                    backdrop: {
                        timeout: 500,
                        sx: { backgroundColor: 'rgba(0, 0, 0, 0.7)' }
                    }
                }}
            >
                <Fade in={open} timeout={400}>
                    <Paper 
                        elevation={5}
                        sx={{ 
                            position: 'absolute', 
                            top: '50%', 
                            left: '50%', 
                            transform: 'translate(-50%, -50%)', 
                            width: 400, 
                            bgcolor: 'background.paper', 
                            borderRadius: 3,
                            p: 0,
                            outline: 'none',
                            boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
                            overflow: 'hidden',
                            transition: 'transform 0.3s ease-out',
                            '&:hover': {
                                transform: 'translate(-50%, -50%) scale(1.01)',
                            }
                        }}
                    >
                        <Box 
                            sx={{ 
                                bgcolor: 'primary.main', 
                                color: 'white',
                                p: 2,
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between'
                            }}
                        >
                            <Typography variant="h6" component="h2">
                                Ingest Python Module
                            </Typography>
                            <Tooltip 
                                title="Enter the exact module name from PyPI that you want to ingest (e.g., 'numpy', 'pandas', 'scikit-learn')"
                                arrow
                                placement="top"
                            >
                                <IconButton size="small" sx={{ color: 'white' }}>
                                    <InfoOutlinedIcon />
                                </IconButton>
                            </Tooltip>
                        </Box>
                        
                        <Box sx={{ p: 3 }}>
                            <Form onSubmit={handleSubmit}>
                                <FormControl fullWidth>
                                    <TextField
                                        name="moduleName"
                                        label="Module name"
                                        placeholder="Enter the exact PyPI package name"
                                        variant="outlined"
                                        fullWidth
                                        margin="normal"
                                        slotProps={{ htmlInput: { "aria-label": "module name" } }}
                                        sx={{ mt: 0 }}
                                    />
                                </FormControl>
                                
                                <Box sx={{ mt: 3, display: 'flex', justifyContent: 'space-between' }}>
                                    <Button
                                        variant="outlined"
                                        onClick={handleClose}
                                    >
                                        Cancel
                                    </Button>
                                    <Button
                                        variant="contained"
                                        color="primary"
                                        type="submit"
                                        disabled={loading}
                                        startIcon={loading ? <CircularProgress size={20} color="inherit" /> : <UploadIcon />}
                                    >
                                        {loading ? 'Processing...' : 'Ingest'}
                                    </Button>
                                </Box>
                            </Form>
                            
                            {successMessage && (
                                <Box sx={{ mt: 2, p: 1.5, bgcolor: 'success.lighter', color: 'success.darker', borderRadius: 1 }}>
                                    <Typography variant="body2">{successMessage}</Typography>
                                </Box>
                            )}
                            
                            {errorMessage && (
                                <Box sx={{ mt: 2, p: 1.5, bgcolor: 'error.lighter', color: 'error.darker', borderRadius: 1 }}>
                                    <Typography variant="body2">{errorMessage}</Typography>
                                </Box>
                            )}
                        </Box>
                    </Paper>
                </Fade>
            </Modal>
        </div>
    );
};

export default UploadModule;
