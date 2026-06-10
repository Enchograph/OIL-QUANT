import React, { useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { getRangeScale } from '../../dashboardLive';

const semanticTransition = {
    duration: 0.42,
    ease: [0.22, 1, 0.36, 1],
};

export default function SemanticRangeChartFrame({ range, children, animate = true }) {
    const previousRangeRef = useRef(range);
    const hasMountedRef = useRef(false);
    const previousRange = previousRangeRef.current;
    const shouldAnimate = animate && hasMountedRef.current && previousRange !== range;
    const initialScale = getRangeScale(previousRange, range);

    useEffect(() => {
        previousRangeRef.current = range;
        hasMountedRef.current = true;
    }, [range]);

    if (!animate) {
        return <div className="semantic-chart-frame">{children}</div>;
    }

    return (
        <motion.div
            key={range}
            className="semantic-chart-frame"
            initial={
                shouldAnimate
                    ? {
                        opacity: 0.82,
                        scaleX: initialScale,
                    }
                    : false
            }
            animate={{ opacity: 1, scaleX: 1 }}
            transition={semanticTransition}
            style={{ transformOrigin: 'right center' }}
        >
            {children}
        </motion.div>
    );
}
