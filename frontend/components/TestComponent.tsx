'use client';

import Link from "next/link";
import { useState } from "react";

export function TestComponent() {
  const [count, setCount] = useState(0);

  return (
    <div className="p-4">
      <h1 className="text-2xl font-bold">Test Component</h1>
      <p>Count: {count}</p>
      <button onClick={() => setCount(c => c + 1)} className="px-4 py-2 bg-blue-500 text-white rounded">
        Increment
      </button>
      <Link href="/">Go Home</Link>
    </div>
  );
}