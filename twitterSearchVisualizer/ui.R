library('shiny')
library('twitteR')
library('d3Network')
library('plyr')

fluidPage(
  titlePanel("Watch the Conversation"),
  sidebarPanel(
    wellPanel(
      textInput("search", "Search for something interesting!", ""),
      verbatimTextOutput("value"),
      div(class="col-sm-5",actionButton("RunModel", "Run")),
      br(),
      helpText('This web app returns a graph representing the results of your search. 
               Each node, or dot, represents a user and each edge represents a mention connecting them.'),
      br(),
      helpText('Do you want current Tweets or a custom range?'),
      br(),
      radioButtons("time", "Time Frame", choices =c('Current','Custom')),
      conditionalPanel("input.time=='Custom'",
                       helpText('Put in your date range:'),
      dateInput("start", label="Start Date",value=as.Date(Sys.time())-7,
                format = "yyyy-mm-dd", startview = "month"),
      dateInput("end", label="End Date",
                format = "yyyy-mm-dd", startview = "month"))
    )),
  mainPanel(
    h3("Search Results"),
    tags$script(src = 'https://d3js.org/d3.v3.min.js'),
    conditionalPanel('input.RunModel==1',
                     htmlOutput('terms'),
                     htmlOutput('inc'))
  )
)