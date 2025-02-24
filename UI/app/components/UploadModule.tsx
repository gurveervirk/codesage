import React, { useState } from 'react';
import { Button, Modal, Box, FormControl, TextField, CircularProgress } from '@mui/material';
import UploadIcon from '@mui/icons-material/Upload';
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

            fetcher.submit({ module_name: moduleName }, { method: 'post', action: '/api/upload_module' });

            if (fetcher.data) {
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
                variant="contained"
                startIcon={<UploadIcon />}
                onClick={handleOpen}
                sx={{ backgroundColor: 'whitesmoke', color: 'black', ":hover": { backgroundColor: 'ghostwhite' } }}
            >
                Upload Module
            </Button>
            <Modal open={open} onClose={handleClose}>
                <Box sx={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', width: 400, bgcolor: 'background.paper', boxShadow: 24, p: 4 }}>
                    <Form onSubmit={handleSubmit}>
                        <FormControl fullWidth>
                            <TextField
                                name="moduleName"
                                label="Module name"
                                placeholder="Enter the name of python module"
                                slotProps={{ htmlInput: { "aria-label": "module name" } }}
                            />
                        </FormControl>
                        <Button
                            sx={{ mt: 1 }}
                            variant="contained"
                            color="primary"
                            type="submit"
                            disabled={loading}
                        >
                            {loading ? <CircularProgress size={24} /> : 'Process'}
                        </Button>
                    </Form>
                    {successMessage && <p style={{ color: 'green' }}>{successMessage}</p>}
                    {errorMessage && <p style={{ color: 'red' }}>{errorMessage}</p>}
                </Box>
            </Modal>
        </div>
    );
};

export default UploadModule;
