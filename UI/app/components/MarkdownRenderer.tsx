import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus, vs } from 'react-syntax-highlighter/dist/cjs/styles/prism';
import remarkGfm from 'remark-gfm';
import { Box, IconButton, Tooltip, Typography, Divider, Chip, Zoom, useTheme } from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckIcon from '@mui/icons-material/Check';
import CodeIcon from '@mui/icons-material/Code';

interface MarkdownRendererProps {
  content: string;
  isUserMessage?: boolean;
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

const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({ content, isUserMessage = false }) => {
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const theme = useTheme();
  
  // Fix for extra newlines: normalize the content
  const normalizedContent = content
    // Replace repeated newlines with a maximum of 2
    .replace(/\n{3,}/g, '\n\n')
    // Ensure consistent line breaks in lists
    .replace(/(\* .*)\n{2,}/g, '$1\n')
    // Fix extra space after code blocks
    .replace(/```\n{2,}/g, '```\n');

  const handleCopyCode = (code: string, index: number) => {
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
        fontFamily: theme.typography.fontFamily,
        fontSize: { xs: '14px', sm: '15px' },
        '& p': { 
          my: 1, 
          lineHeight: 1.6,
          letterSpacing: '0.00938em',
          '&:first-of-type': { mt: 0 },
          '&:last-child': { mb: 0 },
        },
        '& a': { 
          color: isUserMessage ? 'rgba(255,255,255,0.85)' : 'primary.main', 
          textDecoration: 'none',
          fontWeight: 500,
          borderBottom: '1px dashed',
          borderColor: isUserMessage ? 'rgba(255,255,255,0.5)' : 'primary.main',
          transition: 'all 0.2s ease',
          '&:hover': { 
            textDecoration: 'none',
            borderBottom: '1px solid',
            opacity: 0.9,
          } 
        },
        '& ul, & ol': { 
          pl: 2, 
          my: 1,
          '& li': { 
            mb: 0.5, 
            pl: 0.5 
          },
        },
        '& blockquote': { 
          borderLeft: '4px solid', 
          borderColor: isUserMessage ? 'rgba(255,255,255,0.5)' : 'primary.light',
          pl: 1.5, 
          py: 0.2,
          my: 1,
          color: isUserMessage ? 'rgba(255,255,255,0.85)' : 'text.secondary',
          bgcolor: isUserMessage ? 'rgba(255,255,255,0.1)' : 'action.hover',
          borderRadius: '4px',
          fontStyle: 'italic'
        },
        '& h1, & h2, & h3, & h4, & h5, & h6': {
          borderBottom: isUserMessage ? 'none' : '1px solid',
          borderColor: 'divider',
          pb: 0.5,
          mt: 2,
          mb: 1,
          fontWeight: 600,
          letterSpacing: '-0.01em',
          lineHeight: 1.3,
          color: isUserMessage ? 'primary.contrastText' : 'text.primary',
        },
        '& img': {
          maxWidth: '100%',
          borderRadius: '8px',
          my: 1.5,
          boxShadow: '0 4px 14px rgba(0,0,0,0.1)'
        },
        '& hr': {
          my: 2,
          border: 'none',
          height: '1px',
          bgcolor: isUserMessage ? 'rgba(255,255,255,0.3)' : 'divider',
        },
        '& table': {
          borderCollapse: 'separate',
          borderSpacing: 0,
          width: '100%',
          my: 1.5,
          borderRadius: '8px',
          overflow: 'hidden',
          boxShadow: '0 2px 8px rgba(0,0,0,0.05)'
        },
        '& th, & td': {
          border: '1px solid',
          borderColor: isUserMessage ? 'rgba(255,255,255,0.2)' : 'divider',
          p: 1
        },
        '& th': {
          bgcolor: isUserMessage ? 'rgba(255,255,255,0.1)' : 'background.default',
          fontWeight: 600,
          fontSize: '0.9rem'
        },
        '& tr:nth-of-type(even)': {
          bgcolor: isUserMessage ? 'rgba(255,255,255,0.05)' : 'action.hover'
        }
      }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children, ...props }: HeadingProps) => (
            <Typography component="h1" variant="h5" gutterBottom fontWeight={600} {...props}>
              {children}
            </Typography>
          ),
          h2: ({ children, ...props }: HeadingProps) => (
            <Typography component="h2" variant="h6" gutterBottom fontWeight={600} {...props}>
              {children}
            </Typography>
          ),
          h3: ({ children, ...props }: HeadingProps) => (
            <Typography component="h3" variant="subtitle1" gutterBottom fontWeight={600} {...props}>
              {children}
            </Typography>
          ),
          h4: ({ children, ...props }: HeadingProps) => (
            <Typography component="h4" variant="subtitle2" gutterBottom fontWeight="bold" {...props}>
              {children}
            </Typography>
          ),
          h5: ({ children, ...props }: HeadingProps) => (
            <Typography component="h5" variant="body1" gutterBottom fontWeight="bold" {...props}>
              {children}
            </Typography>
          ),
          h6: ({ children, ...props }: HeadingProps) => (
            <Typography component="h6" variant="body2" gutterBottom fontWeight="bold" {...props}>
              {children}
            </Typography>
          ),
          hr: () => <Divider sx={{ my: 2 }} />,
          p: ({ children }) => {
            // Don't add extra spacing for empty paragraphs
            if (React.Children.count(children) === 0 || 
               (React.Children.count(children) === 1 && React.Children.toArray(children)[0] === '')) {
              return null;
            }
            
            return (
              <Typography component="p" variant="body1" sx={{ my: 1, lineHeight: 1.7 }}>
                {children}
              </Typography>
            );
          },
          code({ inline, className, children, ...props }: CodeProps) {
            const match = /language-(\w+)/.exec(className || '');
            const code = String(children).replace(/\n$/, '');
            
            if (!inline && match) {
              // Assign a unique index to each code block
              const currentIndex = codeBlockIndex++;
              const language = match[1];
              
              return (
                <Box sx={{ 
                  position: "relative", 
                  mt: 2, 
                  mb: 2, 
                  borderRadius: "10px", 
                  overflow: "hidden", 
                  boxShadow: isUserMessage ? 
                    '0 6px 18px rgba(0,0,0,0.2)' : 
                    '0 6px 18px rgba(0,0,0,0.12)',
                  transform: "translateZ(0)",
                  transition: "all 0.2s ease",
                  maxWidth: "100%",
                }}>
                  <Box 
                    sx={{ 
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      bgcolor: isUserMessage ? 'rgba(0, 0, 0, 0.4)' : 'rgba(30, 30, 30, 0.95)',
                      px: 2,
                      py: 1,
                      borderBottom: '1px solid rgba(255,255,255,0.1)'
                    }}
                  >
                    <Box display="flex" alignItems="center">
                      <CodeIcon sx={{ color: '#E4E4E4', fontSize: 16, mr: 1, opacity: 0.7 }} />
                      <Chip 
                        label={language} 
                        size="small" 
                        sx={{ 
                          bgcolor: 'rgba(255,255,255,0.1)', 
                          color: '#E4E4E4',
                          fontSize: '0.7rem',
                          height: 20,
                          borderRadius: '10px',
                          textTransform: 'lowercase'
                        }} 
                      />
                    </Box>
                    <Tooltip 
                      title={copiedIndex === currentIndex ? "Copied!" : "Copy code"} 
                      TransitionComponent={Zoom}
                      arrow
                      placement="top"
                    >
                      <IconButton 
                        size="small" 
                        onClick={() => handleCopyCode(code, currentIndex)}
                        sx={{ 
                          color: '#E4E4E4',
                          padding: '4px',
                          borderRadius: '6px',
                          '&:hover': { 
                            bgcolor: 'rgba(255,255,255,0.15)',
                          },
                          transition: 'all 0.2s ease'
                        }}
                      >
                        {copiedIndex === currentIndex ? 
                          <CheckIcon fontSize="small" sx={{ fontSize: 16 }} /> : 
                          <ContentCopyIcon fontSize="small" sx={{ fontSize: 16 }} />
                        }
                      </IconButton>
                    </Tooltip>
                  </Box>
                  <SyntaxHighlighter
                    style={isUserMessage ? vs : vscDarkPlus as any}
                    language={match[1]}
                    PreTag="div"
                    customStyle={{ 
                      margin: 0,
                      padding: '12px 16px',
                      borderRadius: 0,
                      fontSize: '0.85rem',
                      lineHeight: 1.5,
                      backgroundColor: isUserMessage ? 'rgba(0, 0, 0, 0.3)' : undefined,
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
                  backgroundColor: isUserMessage ? 
                    'rgba(255, 255, 255, 0.2)' : 
                    'rgba(175, 184, 193, 0.2)',
                  padding: '0.2em 0.4em',
                  borderRadius: '4px',
                  fontSize: '85%',
                  fontFamily: '"JetBrains Mono", "Fira Code", monospace',
                  fontWeight: 500,
                  color: isUserMessage ? 'white' : undefined,
                }}
                {...props}
              >
                {children}
              </code>
            );
          }
        }}
      >
        {normalizedContent}
      </ReactMarkdown>
    </Box>
  );
};

export default MarkdownRenderer;