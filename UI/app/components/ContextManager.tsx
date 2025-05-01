import React, { useState, useEffect } from 'react';
import { 
  Box, 
  List, 
  ListItem, 
  ListItemText, 
  ListItemButton, 
  IconButton, 
  Typography, 
  Dialog, 
  DialogTitle, 
  DialogActions,
  CircularProgress,
  Button,
  Paper
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import RefreshIcon from '@mui/icons-material/Refresh';
import AddIcon from '@mui/icons-material/Add';

interface Context {
  id: string;
  title: string;
  date: string;
}

interface ContextManagerProps {
  onContextLoad: (contextId: string, chatHistory: string[]) => void;
  onContextReset: () => void;
}

const ContextManager: React.FC<ContextManagerProps> = ({ onContextLoad, onContextReset }) => {
  const [contexts, setContexts] = useState<Context[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [contextToDelete, setContextToDelete] = useState<string | null>(null);

  // Fetch available contexts
  const fetchContexts = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/get-contexts');
      if (!response.ok) {
        throw new Error('Failed to fetch contexts');
      }
      const data = await response.json();
      
      // Process contexts from dictionary format (ctx_id: title) to array format
      const contextsArray = Object.entries(data.contexts || {}).map(([id, title]) => ({
        id,
        title: title as string,
        date: new Date().toLocaleDateString() // Date information is not provided by the API
      }));
      
      setContexts(contextsArray);
    } catch (err) {
      setError('Error loading contexts: ' + (err instanceof Error ? err.message : String(err)));
      console.error('Error fetching contexts:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchContexts();
  }, []);

  // Handle context loading
  const handleLoadContext = async (contextId: string) => {
    setLoading(true);
    try {
      const response = await fetch('/api/load-context', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ id: contextId }),
      });
      
      if (!response.ok) {
        throw new Error('Failed to load context');
      }
      
      const data = await response.json();
      
      // Pass the chat history to the parent component
      // The chat history is now a simple array of strings
      // Even indices are user messages, odd indices are AI messages
      onContextLoad(contextId, data.chat_history);
    } catch (err) {
      setError('Error loading context: ' + (err instanceof Error ? err.message : String(err)));
      console.error('Error loading context:', err);
    } finally {
      setLoading(false);
    }
  };

  // Handle context reset
  const handleResetContext = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/reset-context', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      
      if (!response.ok) {
        throw new Error('Failed to reset context');
      }
      
      onContextReset();
    } catch (err) {
      setError('Error resetting context: ' + (err instanceof Error ? err.message : String(err)));
      console.error('Error resetting context:', err);
    } finally {
      setLoading(false);
    }
  };

  // Handle context deletion
  const confirmDeleteContext = (contextId: string) => {
    setContextToDelete(contextId);
    setDeleteDialogOpen(true);
  };

  const handleDeleteContext = async () => {
    if (!contextToDelete) return;
    
    setLoading(true);
    try {
      const response = await fetch('/api/delete-context', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ id: contextToDelete }),
      });
      
      if (!response.ok) {
        throw new Error('Failed to delete context');
      }
      
      // Remove deleted context from the list
      setContexts(contexts.filter(ctx => ctx.id !== contextToDelete));
      setDeleteDialogOpen(false);
      setContextToDelete(null);
    } catch (err) {
      setError('Error deleting context: ' + (err instanceof Error ? err.message : String(err)));
      console.error('Error deleting context:', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box>
      {/* New Conversation Button - Separated and prominent */}
      <Paper
        elevation={0}
        sx={{
          mb: 2,
          borderRadius: 2,
          border: '1px solid',
          borderColor: 'primary.light',
          overflow: 'hidden',
          transition: 'all 0.2s ease',
          '&:hover': {
            borderColor: 'primary.main',
            boxShadow: '0 2px 8px rgba(0,0,0,0.08)',
            bgcolor: 'action.hover',
          },
        }}
      >
        <Button 
          fullWidth
          startIcon={<AddIcon />}
          onClick={handleResetContext}
          sx={{
            py: 1,
            textTransform: 'none',
            justifyContent: 'flex-start',
            fontWeight: 500,
            color: 'primary.main',
          }}
        >
          New Conversation
        </Button>
      </Paper>

      {/* Conversation History Header */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h6">Conversation History</Typography>
        <IconButton onClick={fetchContexts} title="Refresh conversations">
          <RefreshIcon />
        </IconButton>
      </Box>

      {error && (
        <Typography color="error" variant="body2" mb={2}>
          {error}
        </Typography>
      )}

      {loading ? (
        <Box display="flex" justifyContent="center" my={2}>
          <CircularProgress size={24} />
        </Box>
      ) : (
        <List sx={{ width: '100%' }}>
          {contexts.length > 0 ? (
            contexts.map((context) => (
              <ListItem 
                key={context.id}
                secondaryAction={
                  <IconButton edge="end" onClick={() => confirmDeleteContext(context.id)}>
                    <DeleteIcon />
                  </IconButton>
                }
                disablePadding
              >
                <ListItemButton onClick={() => handleLoadContext(context.id)}>
                  <ListItemText 
                    primary={context.title}
                    secondary={context.date}
                    primaryTypographyProps={{
                      noWrap: true,
                      style: { maxWidth: '170px' }
                    }}
                  />
                </ListItemButton>
              </ListItem>
            ))
          ) : (
            <Typography variant="body2" color="text.secondary" align="center">
              No previous conversations
            </Typography>
          )}
        </List>
      )}

      {/* Delete confirmation dialog */}
      <Dialog
        open={deleteDialogOpen}
        onClose={() => setDeleteDialogOpen(false)}
      >
        <DialogTitle>
          Delete this conversation?
        </DialogTitle>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleDeleteContext} color="error">Delete</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default ContextManager;