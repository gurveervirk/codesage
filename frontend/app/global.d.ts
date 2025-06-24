declare namespace JSX {
  interface IntrinsicElements {
    "md-circular-progress": React.DetailedHTMLProps<
      React.HTMLAttributes<HTMLElement>,
      HTMLElement
    > & {
      indeterminate?: boolean;
    };
    "md-filled-text-field": React.DetailedHTMLProps<
      React.HTMLAttributes<HTMLElement>,
      HTMLElement
    > & {
      value?: string;
      label?: string;
      onInput?: (event: Event) => void;
    };
    "md-filled-button": React.DetailedHTMLProps<
      React.HTMLAttributes<HTMLElement>,
      HTMLElement
    > & {
      onclick?: (event: Event) => void;
    };
  }
}
