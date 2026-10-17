import * as React from "react";

export function Spinner({ className, ...props }: React.ComponentProps<"svg">) {
  return (
    <svg
      aria-label='Loading'
      viewBox='0 0 24 24'
      fill='none'
      stroke='currentColor'
      strokeWidth='2'
      strokeLinecap='round'
      strokeLinejoin='round'
      className={className}
      {...props}>
      <path d='M12 2a10 10 0 1 0 10 10' />
    </svg>
  );
}
