"use client";

import { Button } from "@/components/ui/button";

export default function Default() {
  return (
    <div className='flex min-h-screen w-full items-center justify-center bg-background p-8'>
      <div className='flex items-center gap-4'>
        <Button size='xl'>Button</Button>
        <Button size='xl' variant='outline'>
          Secondary
        </Button>
      </div>
    </div>
  );
}
