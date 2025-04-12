import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/cjs/styles/prism';
import remarkGfm from 'remark-gfm';
import { Box, IconButton, Tooltip, Typography, Divider, Chip, Zoom } from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckIcon from '@mui/icons-material/Check';
import CodeIcon from '@mui/icons-material/Code';

interface MarkdownRendererProps {
  content: string;
}

interface CodeProps {
  inline?: boolean;
  className?: string;
  children?: React.ReactNode;
  node?: any;
}

interface HeadingProps {
  children?: React.ReactNode;
  node?: any;
}

const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({ content }) => {
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  const handleCopyCode = (code: string, index: number) => {
    // Use modern clipboard API with fallback
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(code)
        .then(() => {
          setCopiedIndex(index);
          setTimeout(() => setCopiedIndex(null), 2000);
        })
        .catch(err => {
          console.error('Failed to copy: ', err);
          fallbackCopyTextToClipboard(code, index);
        });
    } else {
      fallbackCopyTextToClipboard(code, index);
    }
  };

  const fallbackCopyTextToClipboard = (code: string, index: number) => {
    const textarea = document.createElement('textarea');
    textarea.value = code;
    textarea.style.position = 'fixed';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    
    try {
      const successful = document.execCommand('copy');
      if (successful) {
        setCopiedIndex(index);
        setTimeout(() => setCopiedIndex(null), 2000);
      } else {
        console.error('Failed to copy');
      }
    } catch (err) {
      console.error('Failed to copy: ', err);
    }
    
    document.body.removeChild(textarea);
  };

  // Counter for tracking code block instances
  let codeBlockIndex = 0;

  return (
    <Box 
      className="markdown-body" 
      sx={{ 
        fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
        fontSize: '15px',
        '& p': { my: 1.2, lineHeight: 1.6, letterSpacing: '0.00938em' },
        '& a': { 
          color: 'primary.main', 
          textDecoration: 'none',
          fontWeight: 500,
          borderBottom: '1px dashed',
          borderColor: 'primary.main',
          transition: 'all 0.2s ease',
          '&:hover': { 
            textDecoration: 'none',
            borderBottom: '1px solid',
            opacity: 0.8,
          } 
        },
        '& ul, & ol': { pl: 2, my: 1.2 },
        '& li': { mb: 0.8, lineHeight: 1.6 },
        '& blockquote': { 
          borderLeft: '4px solid', 
          borderColor: 'primary.light',
          pl: 2, 
          py: 0.5,
          my: 1.5,
          color: 'text.secondary',
          bgcolor: 'action.hover',
          borderRadius: '4px',
          fontStyle: 'italic'
        },
        '& h1, & h2, & h3, & h4, & h5, & h6': {
          borderBottom: '1px solid',
          borderColor: 'divider',
          pb: 0.5,
          mt: 2.5,
          mb: 1.2,
          fontWeight: 600,
          letterSpacing: '-0.01em',
          lineHeight: 1.3,
        },
        '& img': {
          maxWidth: '100%',
          borderRadius: '8px',
          my: 1.5,
          boxShadow: '0 4px 14px rgba(0,0,0,0.1)'
        },
        '& hr': {
          my: 2.5,
          border: 'none',
          height: '1px',
          bgcolor: 'divider',
        },
        '& table': {
          borderCollapse: 'separate',
          borderSpacing: 0,
          width: '100%',
          my: 2,
          borderRadius: '8px',
          overflow: 'hidden',
          boxShadow: '0 2px 8px rgba(0,0,0,0.05)'
        },
        '& th, & td': {
          border: '1px solid',
          borderColor: 'divider',
          p: 1.2
        },
        '& th': {
          bgcolor: 'background.default',
          fontWeight: 600,
          fontSize: '0.9rem'
        },
        '& tr:nth-of-type(even)': {
          bgcolor: 'action.hover'
        }
      }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children, ...props }: HeadingProps) => (
            <Typography component="h1" variant="h4" gutterBottom fontFamily="'Inter', sans-serif" fontWeight={600} {...props}>
              {children}
            </Typography>
          ),
          h2: ({ children, ...props }: HeadingProps) => (
            <Typography component="h2" variant="h5" gutterBottom fontFamily="'Inter', sans-serif" fontWeight={600} {...props}>
              {children}
            </Typography>
          ),
          h3: ({ children, ...props }: HeadingProps) => (
            <Typography component="h3" variant="h6" gutterBottom fontFamily="'Inter', sans-serif" fontWeight={600} {...props}>
              {children}
            </Typography>
          ),
          h4: ({ children, ...props }: HeadingProps) => (
            <Typography component="h4" variant="subtitle1" gutterBottom fontWeight="bold" fontFamily="'Inter', sans-serif" {...props}>
              {children}
            </Typography>
          ),
          h5: ({ children, ...props }: HeadingProps) => (
            <Typography component="h5" variant="subtitle2" gutterBottom fontWeight="bold" fontFamily="'Inter', sans-serif" {...props}>
              {children}
            </Typography>
          ),
          h6: ({ children, ...props }: HeadingProps) => (
            <Typography component="h6" variant="body2" gutterBottom fontWeight="bold" fontFamily="'Inter', sans-serif" {...props}>
              {children}
            </Typography>
          ),
          hr: () => <Divider sx={{ my: 2.5 }} />,
          code({ inline, className, children, ...props }: CodeProps) {
            const match = /language-(\w+)/.exec(className || '');
            const code = String(children).replace(/\n$/, '');
            
            if (!inline && match) {
              // Assign a unique index to each code block
              const currentIndex = codeBlockIndex++;
              
              return (
                <Box sx={{ 
                  position: "relative", 
                  mt: 2.5, 
                  mb: 2.5, 
                  borderRadius: "10px", 
                  overflow: "hidden", 
                  boxShadow: "0 6px 18px rgba(0,0,0,0.12)",
                  transform: "translateZ(0)",
                  transition: "all 0.2s ease"
                }}>
                  <Box 
                    sx={{ 
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      bgcolor: 'rgba(30, 30, 30, 0.95)',
                      px: 2,
                      py: 1.2,
                      borderBottom: '1px solid rgba(255,255,255,0.1)'
                    }}
                  >
                    <Box display="flex" alignItems="center">
                      <CodeIcon sx={{ color: '#E4E4E4', fontSize: 18, mr: 1, opacity: 0.7 }} />
                      <Chip 
                        label={match[1]} 
                        size="small" 
                        sx={{ 
                          bgcolor: 'rgba(255,255,255,0.1)', 
                          color: '#E4E4E4',
                          fontSize: '0.75rem',
                          height: 24,
                          borderRadius: '12px',
                          textTransform: 'lowercase'
                        }} 
                      />
                    </Box>
                    <Tooltip 
                      title={copiedIndex === currentIndex ? "Copied!" : "Copy code"} 
                      TransitionComponent={Zoom}
                      arrow
                    >
                      <IconButton 
                        size="small" 
                        onClick={() => handleCopyCode(code, currentIndex)}
                        sx={{ 
                          color: '#E4E4E4',
                          padding: '5px',
                          borderRadius: '8px',
                          '&:hover': { 
                            bgcolor: 'rgba(255,255,255,0.15)',
                            transform: 'translateY(-1px)'
                          },
                          transition: 'all 0.2s ease'
                        }}
                      >
                        {copiedIndex === currentIndex ? 
                          <CheckIcon fontSize="small" /> : 
                          <ContentCopyIcon fontSize="small" />
                        }
                      </IconButton>
                    </Tooltip>
                  </Box>
                  <SyntaxHighlighter
                    style={vscDarkPlus as any}
                    language={match[1]}
                    PreTag="div"
                    customStyle={{ 
                      margin: 0,
                      padding: '16px 20px',
                      borderRadius: 0,
                      fontSize: '0.9rem',
                      lineHeight: 1.6
                    }}
                    {...props}
                  >
                    {code}
                  </SyntaxHighlighter>
                </Box>
              );
            }
            
            return (
              <code 
                className={className} 
                style={{
                  backgroundColor: 'rgba(175, 184, 193, 0.2)',
                  padding: '0.2em 0.4em',
                  borderRadius: '4px',
                  fontSize: '85%',
                  fontFamily: '"JetBrains Mono", "Fira Code", ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, monospace',
                  fontWeight: 500
                }}
                {...props}
              >
                {children}
              </code>
            );
          }
        }}
      >
        {content}
      </ReactMarkdown>
    </Box>
  );
};

export default MarkdownRenderer;