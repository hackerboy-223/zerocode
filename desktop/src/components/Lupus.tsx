import { useId } from "react";
import { motion } from "framer-motion";

interface LupusProps {
  size?: "small" | "large";
  calm?: boolean;
}

export default function Lupus({ size = "small", calm = false }: LupusProps) {
  const id = useId().replace(/:/g, "");
  const metalGradient = id + "-metal";
  const blueGradient = id + "-blue";
  return (
    <motion.div
      className={"lupus lupus-" + size + (calm ? " lupus-calm" : "")}
      initial={{ opacity: 0, scale: 0.92, y: 5 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
      aria-label="LUPUS, le veilleur ZeroCode"
    >
      <svg viewBox="0 0 120 112" role="img" aria-hidden="true">
        <defs>
          <linearGradient id={metalGradient} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#f9fbff" />
            <stop offset="100%" stopColor="#aeb9c8" />
          </linearGradient>
          <linearGradient id={blueGradient} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#69b7ff" />
            <stop offset="100%" stopColor="#3278d6" />
          </linearGradient>
        </defs>
        <path className="wolf-ear" d="M25 52 13 12 46 34M95 52 107 12 74 34" fill={"url(#" + metalGradient + ")"} stroke="#7b8797" strokeWidth="3" strokeLinejoin="round" />
        <path d="M25 47 28 25 44 42M95 47 92 25 76 42" fill="none" stroke="#6aaeff" strokeWidth="3" strokeLinecap="round" />
        <path d="M22 47 Q60 17 98 47 L91 84 Q84 102 60 105 Q36 102 29 84Z" fill="url(#lupusMetal)" stroke="#748195" strokeWidth="3" />
        <path d="M33 54 Q60 38 87 54 L83 78 Q60 92 37 78Z" fill="#253144" />
        <path className="wolf-eye" d="M42 63 Q50 55 57 63" fill="none" stroke="#67bdff" strokeWidth="4" strokeLinecap="round" />
        <path className="wolf-eye" d="M63 63 Q70 55 78 63" fill="none" stroke="#67bdff" strokeWidth="4" strokeLinecap="round" />
        <path d="M51 78 Q60 72 69 78 L64 85 56 85Z" fill={"url(#" + blueGradient + ")"} />
        <path d="M60 85 60 91M45 86 54 91M75 86 66 91" stroke="#57677b" strokeWidth="2.6" strokeLinecap="round" fill="none" />
        <path d="M18 72 30 76M102 72 90 76" stroke="#6aaeff" strokeWidth="3" strokeLinecap="round" />
        <circle cx="60" cy="47" r="3" fill="#6aaeff" />
      </svg>
      {size === "large" && <div className="lupus-caption">LUPUS <span>LE VEILLEUR</span></div>}
    </motion.div>
  );
}
