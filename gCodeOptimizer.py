'''
Created on Nov 12, 2014

@author: adamsb
'''



import sqlite3, math, time, sys
import re

class Optimizer:
    dbConn = None
    dbCursor = None
    
    outputGCode = []
    startTime = None
    originalTraversal = 0
    optimizedTraversal = 0
    lastPosition = (0,0)
    deletedLines = 0
 
    
    def gCodeEta(self, done, total, now, rateEstimate):
        left = total-done
        return (rateEstimate/left) * ((left*(left+1))/2)
    
    def dedupEta(self, done, total, now, rateEstimate):
        return (rateEstimate/done) * ((total*(total+1)/2) - (done*(done+1)/2))
        
    def secToString(self, seconds):
        output = ""
        hours = int(seconds / (60*60))
        if hours > 0:
            output += str(hours) +"h"
            seconds = seconds - (hours*(60*60))
        minutes = int(seconds / (60))
        if minutes > 0:
            output += str(minutes) + "m"
            seconds = seconds - (minutes*60)
        output += str(int(seconds)) +"s"
        return output
        
            
    
    def progressBar(self, done, total, text="", showRate=False, etaFunc=None, rateUnits="items/sec"):
    
        
        if done > total: 
            return
    
        now = time.time()
        if self.startTime is None:
            self.startTime = now
            self.lastTime = now
            self.singleRate = "??"
            self.rateLastComputed = now
            self.eta = 0
            self.rateEstimate = None
        percent_done = float(done) / float(total)
    
        bar = int(math.floor(percent_done * 30))

        status_bar="\r" + text+ "[" + ("=" * bar)
       
        if bar < 30:
            status_bar += ">"
            status_bar +=(" " * (30-bar));
        else:
            status_bar += "="

        disp = "{:3.0f}".format(percent_done*100)

        status_bar += "] "+ disp +"%  "+str(done)+"/"+str(total)

        elapsed = now - self.startTime;
        rateEstimate = (now-self.lastTime)
        if (elapsed < 0.5):  #Prime the rateEstimate
            self.rateLastComputed = now
            if (rateEstimate == 0):
                pass
            elif (self.rateEstimate is None):
                
                self.rateEstimate = rateEstimate
            else:
                self.rateEstimate = (rateEstimate*0.1) + (self.rateEstimate*0.9)
                
        elif ((now - self.rateLastComputed) > 0.5):  #Once the estimate is primed, start calculating eta.
            self.rateLastComputed = now
            rateEstimate = (now-self.lastTime)
            if self.rateEstimate is None:
                self.rateEstimate = rateEstimate
            else:
                self.rateEstimate = (rateEstimate*0.01) + (self.rateEstimate*0.99)
            
            if etaFunc is not None:
                self.eta = etaFunc(done, total, now, self.rateEstimate)
            else:
                self.eta = self.rateEstimate * (total - done)
             
            self.singleRate = str(round(1 / (now - self.lastTime), 2))
            
        

        status_bar += " " + self.secToString(self.eta) +" remaining, " + self.secToString(elapsed) + " elapsed." 
        
        if (showRate):
            status_bar += " ("+self.singleRate+" "+rateUnits+")"
        status_bar += "      "
        sys.stdout.write(status_bar)
        sys.stdout.flush()
        self.lastTime = now

        if (done == total):
            print
            self.startTime = None
        
    def getNumberAfterChar(self, line, character):
        matches = re.search(character+'([-+]?[0-9]*\.?[0-9]+)', line);
        if matches:
            if len(matches.groups()) > 1:
                print "\nERROR: Multiple parameters with same name on a line.\n"
                exit -1
            return matches.group(1)
        else:
            return False
    
    def getLength(self, start, end):
        return math.sqrt(math.pow(start[0] - end[0], 2) + math.pow(start[1] - end[1], 2));    
    
    def getPosition(self, line):
        x = self.getNumberAfterChar(line, 'X')
        y = self.getNumberAfterChar(line, 'Y')
        
        if (x is False or y is False):
            return None
        return (float(x), float(y))
        
    def isCoincident(self, point1, point2):
        return (point1[0] == point2[0]) and (point1[1] == point2[1])
    
    def getLinesCount(self):
        self.dbCursor.execute("SELECT COUNT(*) from lines")
        result = self.dbCursor.fetchone();
        return result[0]
    
    def getNearest(self, location):
        self.dbCursor.execute('''
            SELECT num, start_x, start_y, end_x, end_y,
             length, power, feedrate, 
             (start_x - :x )*(start_x - :x) + (start_y - :y)*(start_y - :y) as distance_start,
             (end_x - :x)*(end_x - :x) + (end_y - :y)*(end_y - :y) as distance_end
             FROM lines ORDER BY min(distance_start, distance_end), length LIMIT 1''', {"x": location[0], "y": location[1]})
        line = self.dbCursor.fetchone()
        if line is not None:
            self.dbCursor.execute('DELETE from lines where num = ?', (line['num'],))
        return line
    
    def pointExists(self, point1, point2, feedRate, power):
        self.dbCursor.execute('''
            SELECT COUNT(*) FROM lines WHERE 
                ((start_x = :x1 AND start_y = :y1 AND end_x = :x2 AND end_y = :y2) OR
                (start_x = :x2 AND start_y = :y2 AND end_x = :x1 AND end_y = :y1)) AND
                power = :power AND feedrate = :feedRate''', {"x1":point1[0], "y1": point1[1], "x2": point2[0], "y2": point2[1], "power": power, "feedRate": feedRate})
        result = self.dbCursor.fetchone();
        return result[0] > 0

    
    def moveTo(self, location, feedRate, code="G1"):
        self.outputf.write(code + " X" + str(location[0]) + " Y" + str(location[1]) + " F" + str(feedRate) + "\n")
        
    def laserOn(self, power):
        self.outputf.write("M3 S"+str(power)+"\n")
    
    def laserOff(self):
        self.outputf.write("M5\n")
        
    def __init__(self, inFileName, outFileName, traversalRate, deleteDuplicates=False, sectionStartRegex="^; Start of path", sectionEndRegex="^; End of path"):
        self.dbConn = sqlite3.connect(':memory:')
        self.dbConn.row_factory = sqlite3.Row
        self.dbCursor = self.dbConn.cursor()
        self.traversalRate = traversalRate
        self.dbCursor.execute('''CREATE TABLE lines
            (num INT, start_x DOUBLE, start_y DOUBLE, end_x DOUBLE, end_y DOUBLE,
             length DOUBLE, power DOUBLE, feedrate DOUBLE);''')
        
        inputf = open (inFileName, 'r')
        self.sectionFound = False
        self.outputf = open(outFileName, 'w')
        with inputf:
            totalInputLines = sum(1 for _ in inputf)
        inputf = open (inFileName, 'r')
        
        active = False
        self.lastPosition = (0, 0)
        power = 0
        sectionOpen = False
        lineNum = 0
        feedRate = 100
        
        for line in iter(inputf.readline, ''):
            line = line.rstrip()
            lineNum+=1
            if (re.search(sectionStartRegex, line)):
                if (sectionOpen):
                    self.processGCodeDatabase();
                print "\nFound Section Open: "+line+ "\n"
                self.outputf.write(line + "\n")
                sectionOpen = True
                self.sectionFound = True
            elif (re.search(sectionEndRegex, line)):
                self.processGCodeDatabase();
                sectionOpen = False
                self.outputf.write(line + "\n")
                print "\nFound Section Close: "+line+ "\n"
            elif (not sectionOpen):
                self.outputf.write(line + "\n")
            else:                   
                if (deleteDuplicates):
                    self.progressBar(lineNum, totalInputLines, "Loading Gcode...\t\t", etaFunc=self.dedupEta)
                else:
                    self.progressBar(lineNum, totalInputLines, "Loading GCode...\t\t")
                if len(line) == 0:
                    continue
                elif line[0] == 'G':
                    codeNum = int(self.getNumberAfterChar(line, '^G'));
                    
                    if (codeNum == 0) or (codeNum == 1):
                        headerOpen = False
                        newPosition = self.getPosition(line)
                        if newPosition is None:
                            continue
                        newFeedRate = float(self.getNumberAfterChar(line, 'F'))
                        if newFeedRate:
                            feedRate = newFeedRate
                        length = self.getLength(self.lastPosition, newPosition)
                        values = (lineNum,
                             self.lastPosition[0], self.lastPosition[1],
                             newPosition[0], newPosition[1],
                             length, power, feedRate
                            ) 
                        if active:
                            if deleteDuplicates:
                                if self.pointExists(self.lastPosition, newPosition, feedRate, power):
                                    self.lastPosition = newPosition
                                    self.deletedLines += 1;
                                    continue
                            self.dbCursor.execute('''INSERT INTO lines VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', values)
                        else:
                            self.originalTraversal+=length
                            
                        
                        
                        self.lastPosition = newPosition
                elif line[0] == 'M':
                    
                    codeNum = int(self.getNumberAfterChar(line, '^M'));
                        
                    if (codeNum == 3):
                        newPower = float(self.getNumberAfterChar(line, 'S'))
                        if newPower is not False:
                            power = newPower
                        active = True
                    elif codeNum == 5:
                        active = False
                    
       
        inputf.close()

        self.processGCodeDatabase()
        self.outputf.close()   
            
        
    def processGCodeDatabase(self):
        active = False
        power = 0
        processedLines = 0
        totalLines = self.getLinesCount()
        line = self.getNearest(self.lastPosition)
        
        while line is not None:
            processedLines += 1
            self.progressBar(processedLines, totalLines, "Optimizing GCode...\t\t", showRate=True, rateUnits="lines/sec", etaFunc=self.gCodeEta)
            start = (line['start_x'], line['start_y'])
            end = (line['end_x'], line['end_y'])
            if line['distance_start'] < line['distance_end']:
                
                if not self.isCoincident(self.lastPosition, start):
                    self.laserOff();
                    active = False
                    self.optimizedTraversal += self.getLength(self.lastPosition, start)
                    self.moveTo(start, self.traversalRate, "G0");
                if (active is False) or power != line['power']:
                    power = line['power']
                    self.laserOn(power)
                    active = True
                self.moveTo(end, line['feedRate'])
                self.lastPosition = end
            else:
                if not self.isCoincident(self.lastPosition, end):
                    self.optimizedTraversal += self.getLength(self.lastPosition, end)
                    self.laserOff();
                    active = False
                    self.moveTo(end, self.traversalRate, "G0");
                if (active is False) or power != line['power']:
                    power = line['power']
                    active = True
                    self.laserOn(power)
                self.moveTo(start, line['feedRate'])
                self.lastPosition = start    
            
            line = self.getNearest(self.lastPosition)
     
         

import argparse

parser = argparse.ArgumentParser()

parser.add_argument("inputfile", help="Input GCode file to optimize")
parser.add_argument('outputfile', help="File to write optimized code")
parser.add_argument('-t', '--traversal', help="Traversal rate (defaults to 1000)", type=float, default=1000)
parser.add_argument('-d', '--dedup', help="Delete duplicate lines", action="store_true")
parser.add_argument('--section-start', help="Section start regex", default="^; Start of path")
parser.add_argument('--section-end', help="Section start regex", default="^; End of path")
args = parser.parse_args()

optmzr = Optimizer(args.inputfile, args.outputfile, args.traversal, deleteDuplicates=args.dedup, sectionStartRegex=args.section_start, sectionEndRegex=args.section_end)
print
if (optmzr.sectionFound):
    if (args.dedup):
        print "Removed " + str(optmzr.deletedLines) + " duplicate lines."
    
    print "Original Traversal: " + str(round(optmzr.originalTraversal, 2)) + " ",
    print "Optimized Traversal: " + str(round(optmzr.optimizedTraversal, 2)) + " ",
    print "(" + str(round((optmzr.optimizedTraversal/optmzr.originalTraversal)*100, 2))+ "%)"
else:
    print "WARNING: No optimizing sections found.  Use --section-start and --section-end to define section markers. "


